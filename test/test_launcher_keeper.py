"""The desktop keeper (launcher.keeper) and its controls (launcher.control).

The keeper runs a stand-in server, not app.py: a few lines of http.server that
can be told to behave, crash, hang, ignore the stop request, or start a child
process. That runs every keeper path in seconds. The real app under the keeper
is verified by hand (see the M3.3 notes in the Phase 3 plan).
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from launcher import control, keeper

FAKE_SERVER = r"""
import http.server, os, subprocess, sys, threading, time
port, mode = int(sys.argv[1]), sys.argv[2]
stop_file = os.environ.get("FASTALGO_STOP_FILE")
assert os.environ.get("FASTALGO_DESKTOP") == "1"
answering = mode != "silent"

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not answering:
            time.sleep(60)
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a):
        pass

server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print("fake server up", flush=True)
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    open(os.path.join(os.path.dirname(stop_file), "child.pid"), "w").write(str(child.pid))
started = time.monotonic()
while True:
    if mode == "crash" and time.monotonic() - started > 0.3:
        sys.exit(3)
    if mode == "hang" and time.monotonic() - started > 0.5:
        answering = False
    if mode != "ignore_stop" and mode != "child" and stop_file and os.path.exists(stop_file):
        os.remove(stop_file)
        sys.exit(0)
    time.sleep(0.05)
"""

FAST = keeper.Timing(
    tick=0.05,
    start_grace=0.5,
    start_timeout=3.0,
    health_interval=0.2,
    health_timeout=0.3,
    health_misses=2,
    stop_timeout=1.5,
    port_wait=1.0,
    backoff=(0.1, 0.1, 0.1, 0.1, 0.1),
    crash_limit=3,
    crash_window=60.0,
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _alive(pid: int) -> bool:
    return keeper.process_start_time(pid) is not None


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "FastAlgo"
    app = home / "app"
    app.mkdir(parents=True)
    port = _free_port()
    (app / ".env").write_text(
        f"FLASK_PORT='{port}'\nWEBSOCKET_PORT='{_free_port()}'\nZMQ_PORT='{_free_port()}'\n",
        encoding="utf-8",
    )
    (home / "fake_server.py").write_text(FAKE_SERVER, encoding="utf-8")
    yield home
    # Never leave a stand-in running, whatever a test did.
    paths = keeper.paths_for(home)
    if control.keeper_running(paths):
        control._send(paths, "stop")
        time.sleep(3)
    for name in ("server.json",):
        record = keeper.read_json(paths.run / name) or {}
        if isinstance(record.get("pid"), int) and _alive(record["pid"]):
            keeper.Server(record["pid"], record.get("started")).kill()


def _command(home: Path, mode: str) -> list[str]:
    port = keeper.server_ports(keeper.paths_for(home))["FLASK_PORT"]
    return [sys.executable, str(home / "fake_server.py"), str(port), mode]


def _run_in_thread(home: Path, mode: str, timing: keeper.Timing = FAST):
    k = keeper.Keeper(keeper.paths_for(home), command=_command(home, mode), timing=timing)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("code", k.run()), daemon=True)
    thread.start()
    return k, thread, result


def _log(paths) -> str:
    """The keeper log, or nothing yet: the keeper creates it on its first line."""
    try:
        return paths.keeper_log.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _wait_state(paths, states, timeout=15.0) -> dict:
    return control.wait_for(paths, set(states), timeout)


# --- start, run, stop ----------------------------------------------------------


def test_starts_reports_running_and_stops_cleanly(home):
    paths = keeper.paths_for(home)
    _k, thread, result = _run_in_thread(home, "ok")
    report = _wait_state(paths, {"running"})
    assert report["state"] == "running" and report["supervised"]
    server_pid = report["server_pid"]
    assert _alive(server_pid)
    assert Path(report["log_file"]).read_text(encoding="utf-8").startswith("fake server up")

    control._send(paths, "stop")
    thread.join(timeout=15)
    assert result["code"] == 0
    assert not _alive(server_pid)
    assert control.status(paths)["state"] == "stopped"
    assert not paths.server_pid.exists() and not paths.stop_request.exists()


def test_second_keeper_refuses(home):
    paths = keeper.paths_for(home)
    _k, thread, _result = _run_in_thread(home, "ok")
    _wait_state(paths, {"running"})
    assert keeper.Keeper(paths, command=_command(home, "ok"), timing=FAST).run() == 3
    control._send(paths, "stop")
    thread.join(timeout=15)


def test_restart_command_gives_a_new_server(home):
    paths = keeper.paths_for(home)
    _k, thread, _result = _run_in_thread(home, "ok")
    first = _wait_state(paths, {"running"})["server_pid"]
    control._send(paths, "restart")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        now = control.status(paths)
        if now["state"] == "running" and now["server_pid"] != first:
            break
        time.sleep(0.1)
    assert now["server_pid"] != first and not _alive(first)
    control._send(paths, "stop")
    thread.join(timeout=15)


# --- crashes and hangs ---------------------------------------------------------


def test_crashing_server_is_restarted_then_given_up_on(home):
    paths = keeper.paths_for(home)
    _k, thread, result = _run_in_thread(home, "crash")
    thread.join(timeout=30)
    assert result["code"] == 1
    report = control.status(paths)
    assert report["state"] == "crashed"
    assert report["restarts"] == FAST.crash_limit - 1
    assert "kept stopping" in report["message"]
    log = _log(paths)
    assert log.count("server exited on its own (code 3)") == FAST.crash_limit


def test_auto_restart_off_stops_after_one_crash(home):
    paths = keeper.paths_for(home)
    paths.settings.write_text(json.dumps({"auto_restart": False}), encoding="utf-8")
    _k, thread, result = _run_in_thread(home, "crash")
    thread.join(timeout=15)
    assert result["code"] == 1
    report = control.status(paths)
    assert report["state"] == "crashed" and report["restarts"] == 0
    assert "Automatic restart is off" in report["message"]


def test_hung_server_is_ended_and_restarted(home):
    paths = keeper.paths_for(home)
    _k, thread, _result = _run_in_thread(home, "hang")
    first = _wait_state(paths, {"running"})["server_pid"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and "server is not answering" not in _log(paths):
        time.sleep(0.1)
    assert "server is not answering" in _log(paths)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _alive(first):
        time.sleep(0.1)
    assert not _alive(first)
    control._send(paths, "stop")
    thread.join(timeout=30)


# --- the process tree ---------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="the job object is Windows only")
def test_stop_ends_a_server_that_ignores_it_and_its_children(home):
    paths = keeper.paths_for(home)
    _k, thread, result = _run_in_thread(home, "child")
    server_pid = _wait_state(paths, {"running"})["server_pid"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (paths.run / "child.pid").exists():
        time.sleep(0.05)
    child_pid = int((paths.run / "child.pid").read_text())
    assert _alive(child_pid)

    control._send(paths, "stop")
    thread.join(timeout=20)
    assert result["code"] == 0
    assert not _alive(server_pid)
    assert not _alive(child_pid), "a strategy process outlived the stop"


# --- port taken ----------------------------------------------------------------


def test_port_in_use_is_reported_not_crash_looped(home):
    paths = keeper.paths_for(home)
    port = keeper.server_ports(paths)["FLASK_PORT"]
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", port))
        squatter.listen()
        code = keeper.Keeper(paths, command=_command(home, "ok"), timing=FAST).run()
    assert code == 1
    report = control.status(paths)
    assert report["state"] == "error"
    assert f"Port {port} is used by another program" in report["message"]


# --- a keeper that dies --------------------------------------------------------


def _timing_args(timing: keeper.Timing) -> tuple[str, ...]:
    return (
        "--timing-json",
        json.dumps({k: getattr(timing, k) for k in timing.__dataclass_fields__}),
    )


def test_server_outlives_a_killed_keeper_and_is_taken_over(home):
    """Through control.start, as the panel does: a real detached keeper process."""
    paths = keeper.paths_for(home)
    extra = ("--command-json", json.dumps(_command(home, "ok"))) + _timing_args(FAST)
    assert control.start(paths, extra_args=extra)
    report = _wait_state(paths, {"running"})
    server_pid, keeper_pid = report["server_pid"], report["keeper_pid"]

    # Only the keeper, as a crash would: on Windows os.kill is TerminateProcess
    # on that one process, where taskkill /T would take the server too.
    os.kill(keeper_pid, 9)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and control.keeper_running(paths):
        time.sleep(0.1)
    assert _alive(server_pid), "the server died with its keeper"
    assert control.status(paths)["state"] == "unsupervised"

    assert control.start(paths, extra_args=extra)
    report = _wait_state(paths, {"running"})
    assert report["server_pid"] == server_pid and report["supervised"]

    assert control.stop(paths)
    assert not _alive(server_pid)
    assert control.status(paths)["state"] == "stopped"


def test_a_slow_first_start_is_not_treated_as_a_hang(home):
    """Never answering for less than start_timeout is starting, not hung."""
    paths = keeper.paths_for(home)
    slow = keeper.Timing(**{**FAST.__dict__, "start_timeout": 30.0})
    _k, thread, _result = _run_in_thread(home, "silent", timing=slow)
    deadline = time.monotonic() + 4  # many health intervals, far past health_misses
    while time.monotonic() < deadline:
        time.sleep(0.2)
    log = _log(paths)
    assert "not answering" not in log and "health check missed" not in log
    assert control.status(paths)["state"] == "starting"
    control._send(paths, "stop")
    thread.join(timeout=15)


def test_a_server_that_never_answers_is_restarted_after_the_start_timeout(home):
    paths = keeper.paths_for(home)
    _k, thread, _result = _run_in_thread(home, "silent")  # FAST.start_timeout is 3 s
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and "not answering" not in _log(paths):
        time.sleep(0.1)
    assert "not answering" in _log(paths)
    control._send(paths, "stop")
    thread.join(timeout=30)
