"""OpenScript: every check that guards a run, a setting or a file holds its lock.

Under the eventlet worker each of these sequences ran without yielding, so it
was atomic by accident. Under gthread (and on the development server) the
threads interleave, and each test below drives the interleaving that broke it:

- hosts-15: two creates of one deployment both passed the duplicate check.
- hosts-16: a removal landed while a run was starting and took its settings.
- hosts-17: an unlocked read, change and write of the schedule file dropped
  another deployment's schedule.
- hosts-18: a Pause during a Stop ended the run before it closed its position,
  and the Stop reported "closed and stopped".
- hosts-19: a quick Pause was overwritten by the start's "running" record, so
  the strategy came back after the next restart.
- hosts-20: two restore passes; the refused one cleared the record of a run
  that was running.
- hosts-21: the run and the platform wrote one command file through one shared
  temporary path.
- rest-09: two saves of one script left one's source beside the other's program.
"""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from flask import Flask

import blueprints.openscript as openscript
import blueprints.openscript_runner as runner
import services.openscript_commands as commands
import services.openscript_run_config as run_config
import services.openscript_runner_service as service
import services.openscript_running as running
import utils.session
from services.openscript_deployment import deployment_id

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(run_config, "CONFIG_FILE", tmp_path / "openscript_run_configs.json")
    monkeypatch.setattr(running, "STATE_FILE", tmp_path / "openscript_running.json")
    monkeypatch.setattr(commands, "COMMAND_FILE", tmp_path / "openscript_commands.json")
    monkeypatch.setattr(runner, "SCHEDULES_FILE", tmp_path / "openscript_runner_schedules.json")
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STARTING_RUNS", set())
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    monkeypatch.setattr(service, "CLOSING_RUNS", set(), raising=False)
    monkeypatch.setattr(service, "DELETING_RUNS", set(), raising=False)
    monkeypatch.setattr(service, "_SHUTTING_DOWN", threading.Event(), raising=False)
    return tmp_path


class Child:
    """A run's process: alive until told to go."""

    def __init__(self, pid=4_100_000):
        self.pid = pid
        self.code = None
        self.signals = []

    def poll(self):
        return self.code

    def terminate(self):
        self.signals.append("terminate")
        self.code = 0

    kill = terminate

    def send_signal(self, number):
        self.terminate()


# ---------------------------------------------------------------------------
# hosts-15
# ---------------------------------------------------------------------------


def test_two_creates_of_one_deployment_store_one(stores):
    barrier = threading.Barrier(8)
    results = []
    lock = threading.Lock()

    def create():
        barrier.wait()
        outcome = run_config.write_run_config("a.oscript", "SBIN", "NSE", "1m", deployment="")
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=create) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert sum(ok for ok, _ in results) == 1, results
    refused = [why for ok, why in results if not ok]
    assert all("already deployed" in why for why in refused), refused
    assert len(run_config.all_run_configs()) == 1


# ---------------------------------------------------------------------------
# hosts-16
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(runner.openscript_runner_bp)
    return app.test_client()


def _deploy():
    ok, why = run_config.write_run_config("d.oscript", "SBIN", "NSE", "1m", user_id="trader")
    assert ok, why
    return next(iter(run_config.all_run_configs()))


def test_settings_cannot_be_removed_while_a_run_is_starting(stores, client, monkeypatch):
    deployment = _deploy()
    claimed = threading.Event()
    release = threading.Event()

    def slow_spawn(script, run_id, *args, **kwargs):
        claimed.set()
        release.wait(5)
        with service.PROCESS_LOCK:
            service.RUNNING_RUNS[run_id] = {"process": Child(), "pid": 1, "script": script}
        return True, "started"

    monkeypatch.setattr(service, "_spawn_claimed", slow_spawn)
    starter = threading.Thread(target=lambda: service.start_run(deployment))
    starter.start()
    assert claimed.wait(5)

    answer = client.delete(f"/openscript/runner/config/{deployment}")
    release.set()
    starter.join(5)

    assert answer.status_code == 409
    assert run_config.read_run_config(deployment) is not None, "settings removed under a run"
    assert deployment in service.RUNNING_RUNS


def test_a_start_after_its_settings_were_removed_is_refused(stores, monkeypatch):
    deployment = _deploy()
    real_read = service.read_run_config
    reads = []

    def read_then_removed(name):
        found = real_read(name)
        reads.append(name)
        if len(reads) == 1:
            # A removal that finishes between the start's read and its claim.
            assert run_config.delete_run_config(deployment)[0]
        return found

    spawned = []
    monkeypatch.setattr(service, "read_run_config", read_then_removed)
    monkeypatch.setattr(service, "_spawn_claimed", lambda *a, **k: spawned.append(a) or (True, ""))

    ok, why = service.start_run(deployment)

    assert ok is False
    assert "removed" in why
    assert spawned == []
    assert service.STARTING_RUNS == set()


def test_a_run_still_starting_is_not_reported_as_not_running(stores, client, monkeypatch):
    deployment = _deploy()
    service.STARTING_RUNS.add(deployment)

    answer = client.post(f"/openscript/runner/pause/{deployment}")

    assert answer.status_code == 409
    assert "still starting" in answer.get_json()["message"]


# ---------------------------------------------------------------------------
# hosts-17
# ---------------------------------------------------------------------------


class Scheduler:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def add_job(self, func, trigger=None, id=None, replace_existing=False, **rest):
        with self.lock:
            self.jobs[id] = func

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        with self.lock:
            self.jobs.pop(job_id, None)


class Host:
    IST = runner.IST

    def __init__(self):
        self.SCHEDULER = Scheduler()

    @staticmethod
    def CronTrigger(**fields):
        return fields

    def init_scheduler(self):
        return None


@pytest.fixture
def host(monkeypatch):
    fake = Host()
    monkeypatch.setattr(runner, "_strategy_host", lambda: fake)
    monkeypatch.setattr(runner, "_RESTORED", True)
    return fake


def test_forgetting_one_schedule_never_drops_another(stores, host, client, monkeypatch):
    runner._save_schedules(
        {
            "x.oscript": {"start_time": "09:20", "stop_time": None, "days": ["mon"]},
            "y.oscript": {"start_time": "09:25", "stop_time": None, "days": ["mon"]},
        }
    )
    real_save = runner._save_schedules
    b_started = threading.Event()

    def paused_save(schedules):
        if threading.current_thread().name == "forget":
            # Read done, write pending: the moment the other deployment's
            # schedule is saved, if nothing stops it.
            b_started.wait(5)
            time.sleep(0.3)
        real_save(schedules)

    monkeypatch.setattr(runner, "_save_schedules", paused_save)

    forget = threading.Thread(target=runner._forget_schedule, args=("x.oscript",), name="forget")
    forget.start()
    time.sleep(0.1)
    b_started.set()
    answer = client.post(
        "/openscript/runner/schedule/z.oscript", json={"start_time": "10:00", "days": ["mon"]}
    )
    forget.join(5)

    assert answer.status_code == 200, answer.get_json()
    stored = runner._load_schedules()
    assert sorted(stored) == ["y.oscript", "z.oscript"], stored


def test_the_scheduler_and_the_file_agree_after_racing_changes(stores, host, client):
    name = "r.oscript"
    barrier = threading.Barrier(8)

    def flip(i):
        own = client.application.test_client()
        barrier.wait()
        for _ in range(10):
            if i % 2:
                own.post(f"/openscript/runner/schedule/{name}", json={"start_time": "09:30"})
            else:
                own.delete(f"/openscript/runner/schedule/{name}")

    threads = [threading.Thread(target=flip, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)

    in_file = name in runner._load_schedules()
    on_scheduler = host.SCHEDULER.get_job(f"openscript_start_{name}") is not None
    assert in_file == on_scheduler


# ---------------------------------------------------------------------------
# hosts-18
# ---------------------------------------------------------------------------


def test_a_pause_cannot_cut_short_a_stop_that_is_closing(stores, monkeypatch):
    run_id = deployment_id("c.oscript", "SBIN", "NSE", "1m")
    child = Child()
    service.RUNNING_RUNS[run_id] = {"process": child, "pid": child.pid, "script": "c.oscript"}
    monkeypatch.setattr(service, "CLOSE_SECONDS", 3.0)
    monkeypatch.setattr(service, "CLOSE_LOOK", 0.05)
    monkeypatch.setattr(service, "mark_stopped", lambda run_id: None)

    def terminate_now(process, pid, gentle=5.0, forced=2.0):
        process.terminate()
        return True

    monkeypatch.setattr(service, "_terminate", terminate_now)

    asked = threading.Event()
    monkeypatch.setattr(service, "ask_to_close", lambda rid: (commands.ask(rid), asked.set()))
    closing = {}
    closer = threading.Thread(
        target=lambda: closing.update(result=service.stop_run(run_id, close=True))
    )
    closer.start()
    assert asked.wait(5)

    paused = service.stop_run(run_id)
    # The run reads the instruction, closes its position, says so and leaves.
    commands.record_closed(run_id)
    child.code = 0
    closer.join(5)

    assert paused == (False, service.CLOSING_MESSAGE)
    assert child.signals == [], "the pause ended the run before it closed its position"
    assert closing["result"][0] is True
    assert service.CLOSING_RUNS == set()


def test_a_close_cut_short_by_shutdown_is_not_reported_as_closed(stores, monkeypatch):
    """hosts-18 remainder. The run exits 0 on a stop signal as after a close.

    The worker going down ends a run whatever else is under way, including a
    Stop that is waiting for its close. The run then leaves without having
    closed anything, and its exit looks the same as after a close. The Stop
    must not answer "closed and stopped" for it.
    """
    run_id = deployment_id("c.oscript", "SBIN", "NSE", "1m")
    child = Child()
    service.RUNNING_RUNS[run_id] = {"process": child, "pid": child.pid, "script": "c.oscript"}
    monkeypatch.setattr(service, "CLOSE_SECONDS", 5.0)
    monkeypatch.setattr(service, "CLOSE_LOOK", 0.05)
    stopped = []
    monkeypatch.setattr(service, "mark_stopped", stopped.append)
    monkeypatch.setattr(
        service, "_terminate", lambda process, pid, **k: process.terminate() or True
    )

    asked = threading.Event()
    monkeypatch.setattr(service, "ask_to_close", lambda rid: (commands.ask(rid), asked.set()))
    closing = {}
    closer = threading.Thread(
        target=lambda: closing.update(result=service.stop_run(run_id, close=True))
    )
    closer.start()
    assert asked.wait(5)

    shut = service.stop_run(run_id, forget=False)
    closer.join(5)

    assert shut[0] is True and child.signals == ["terminate"]
    assert closing["result"] == (False, service.CLOSE_UNCONFIRMED_MESSAGE)
    assert stopped == [run_id], "the trader's Stop still stops the deployment"
    assert commands.all_commands() == {}
    assert service.CLOSING_RUNS == set()


def test_a_close_is_refused_while_a_pause_is_stopping_the_run(stores):
    run_id = deployment_id("c.oscript", "SBIN", "NSE", "1m")
    service.RUNNING_RUNS[run_id] = {"process": Child(), "pid": 1, "script": "c.oscript"}
    service.STOPPING_RUNS.add(run_id)

    assert service.stop_run(run_id, close=True) == (False, "That run is already stopping")


def test_shutdown_still_ends_a_run_that_is_closing(stores, monkeypatch):
    """The worker going down is not a trader's Pause: it is never refused."""
    run_id = deployment_id("c.oscript", "SBIN", "NSE", "1m")
    child = Child()
    service.RUNNING_RUNS[run_id] = {"process": child, "pid": child.pid, "script": "c.oscript"}
    service.CLOSING_RUNS.add(run_id)
    monkeypatch.setattr(
        service, "_terminate", lambda process, pid, **k: process.terminate() or True
    )

    ok, _ = service.stop_run(run_id, forget=False)

    assert ok is True
    assert child.signals == ["terminate"]


# ---------------------------------------------------------------------------
# hosts-19
# ---------------------------------------------------------------------------


def test_a_quick_pause_is_the_last_word_on_the_running_record(stores, monkeypatch):
    edits = []
    edits_lock = threading.Lock()

    def mark_running(run_id, pid):
        time.sleep(0.3)  # the start thread is descheduled just here
        with edits_lock:
            edits.append("running")

    def mark_stopped(run_id):
        with edits_lock:
            edits.append("stopped")

    class Popen:
        def __init__(self, *a, **k):
            self.pid = 4_200_000
            self.code = None

        def poll(self):
            return self.code

    monkeypatch.setattr(service, "mark_running", mark_running)
    monkeypatch.setattr(service, "mark_stopped", mark_stopped)
    monkeypatch.setattr(service.subprocess, "Popen", Popen)
    monkeypatch.setattr(service, "runner_program_path", lambda: Path("runner.py"))
    monkeypatch.setattr(service, "_api_key_for", lambda user: None)
    monkeypatch.setattr(service, "LOGS_DIR", stores)
    monkeypatch.setattr(service, "_terminate", lambda process, pid, **k: True)

    run_id = deployment_id("q.oscript", "SBIN", "NSE", "1m")
    starter = threading.Thread(
        target=service.start_run,
        args=("q.oscript",),
        kwargs={"symbol": "SBIN", "exchange": "NSE", "interval": "1m"},
    )
    starter.start()
    deadline = time.monotonic() + 5
    while run_id not in service.RUNNING_RUNS and time.monotonic() < deadline:
        time.sleep(0.005)

    paused = service.stop_run(run_id)
    starter.join(5)

    assert paused[0] is True
    assert edits[-1] == "stopped", f"the stop was overwritten: {edits}"


# ---------------------------------------------------------------------------
# hosts-20
# ---------------------------------------------------------------------------


def test_two_restore_passes_start_once_and_keep_the_record(stores, monkeypatch):
    deployment = _deploy()
    running.mark_running(deployment, 2_147_000_000)  # a process that is gone
    spawns = []

    def slow_spawn(script, run_id, *args, **kwargs):
        time.sleep(0.2)
        spawns.append(run_id)
        with service.PROCESS_LOCK:
            service.RUNNING_RUNS[run_id] = {"process": Child(), "pid": 1, "script": script}
        return True, "started"

    monkeypatch.setattr(service, "_spawn_claimed", slow_spawn)
    barrier = threading.Barrier(2)

    def restore():
        barrier.wait()
        service.restore_runs()

    threads = [threading.Thread(target=restore) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert spawns == [deployment]
    assert deployment in running.all_running(), "a refused pass cleared a running run's record"


def test_restore_schedules_is_single_flight(stores, host, monkeypatch):
    monkeypatch.setattr(runner, "_RESTORED", False)
    calls = []

    def slow_restore_runs():
        calls.append(1)
        time.sleep(0.2)
        return 0, 0

    monkeypatch.setattr(runner, "restore_runs", slow_restore_runs)
    barrier = threading.Barrier(4)

    def restore():
        barrier.wait()
        runner.restore_schedules()

    threads = [threading.Thread(target=restore) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert calls == [1]
    assert runner._RESTORED is True


# ---------------------------------------------------------------------------
# hosts-21
# ---------------------------------------------------------------------------


WRITER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, {root!r})
    import services.openscript_commands as commands
    from services.openscript_deployment import deployment_id

    commands.COMMAND_FILE = Path({path!r})
    run_id = deployment_id("w{n}.oscript", "SBIN", "NSE", "1m")
    for _ in range(200):
        commands.ask(run_id)
        commands.clear(run_id)
    print("DONE")
    """
)


def test_two_processes_writing_the_command_file_leave_it_whole(tmp_path):
    path = tmp_path / "openscript_commands.json"
    writers = [
        subprocess.Popen(
            [sys.executable, "-c", WRITER.format(root=str(ROOT), path=str(path), n=n)],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n in (1, 2)
    ]
    outputs = [w.communicate(timeout=120) for w in writers]

    for (out, err), writer in zip(outputs, writers, strict=True):
        assert writer.returncode == 0, err
        assert "DONE" in out
    json.loads(path.read_text(encoding="utf-8"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_each_write_uses_a_temporary_file_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "COMMAND_FILE", tmp_path / "openscript_commands.json")
    monkeypatch.setattr(running, "STATE_FILE", tmp_path / "openscript_running.json")
    monkeypatch.setattr(run_config, "CONFIG_FILE", tmp_path / "openscript_run_configs.json")
    used = []
    real_replace = os.replace

    def spy(src, dst):
        used.append(Path(src).name)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    run_id = deployment_id("t.oscript", "SBIN", "NSE", "1m")
    commands.ask(run_id)
    commands.ask(run_id)
    running.mark_running(run_id, 1)
    running.mark_running(run_id, 1)
    run_config.write_run_config("t.oscript", "SBIN", "NSE", "1m")

    assert len(used) == 5
    assert len(set(used)) == 5, f"a temporary path was shared: {used}"
    assert all(name.endswith(".tmp") for name in used)


# ---------------------------------------------------------------------------
# rest-09
# ---------------------------------------------------------------------------


def _pair(text):
    source = f"// {text}\nplot(close)\n"
    program = json.dumps({"source": {"hash": openscript._source_hash(source)}, "tag": text})
    return {"source": source, "program": program}


def test_two_saves_of_one_script_leave_a_matching_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    monkeypatch.setattr(openscript, "SCRIPTS_DIR", tmp_path)
    real_replace = os.replace

    def slow_replace(src, dst):
        real_replace(src, dst)
        if str(dst).endswith(".oscript") and "// A" in Path(dst).read_text(encoding="utf-8"):
            # Save A has replaced its source and not yet its program: the
            # moment save B lands in, if nothing keeps it out.
            time.sleep(0.3)

    monkeypatch.setattr(openscript.os, "replace", slow_replace)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(openscript.openscript_bp)
    answers = []

    def save(tag, delay):
        time.sleep(delay)
        answers.append(app.test_client().post("/openscript/pair.oscript", json=_pair(tag)))

    threads = [
        threading.Thread(target=save, args=("A", 0.0)),
        threading.Thread(target=save, args=("B", 0.1)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert all(a.status_code == 200 for a in answers)
    source = (tmp_path / "pair.oscript").read_text(encoding="utf-8")
    program = json.loads((tmp_path / "pair.oscript.program.json").read_text(encoding="utf-8"))
    assert program["source"]["hash"] == openscript._source_hash(source), (
        "the stored program was compiled from a different source"
    )
