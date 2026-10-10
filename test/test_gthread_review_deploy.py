"""Deployment findings from the gthread review.

deploy-restore-leaves-gthread-in-env. ``switch-worker.sh --restore`` put the
original eventlet service file back but left ``OPENALGO_WORKER_CLASS =
'gthread'`` in .env, so the next routine update.sh moved the service straight
back onto gthread. --restore now sets .env back as well.

deploy-smoke-order-check-mis-after-hours. The broker check's order check
placed an MIS order, which the sandbox refuses from the square-off time until
09:00 IST: the whole window a switch is allowed in. It now uses CNC on NSE and
BSE and NRML elsewhere.

deploy-smoke-live-order-detection-inverted. The check took an answer with no
``mode`` key for a sandbox order, but a live order's answer never carries one,
so the warning for an order that reached the broker could not appear.

deploy-tasksmax-never-checked-under-systemd. The launcher looked for a pids
limit only at the cgroup root, where a systemd service's TasksMax never is.

deploy-docker-stop-window-cuts-shutdown-hooks. gunicorn gives a stopping
worker one graceful window, open requests first and worker_exit after, and on
Docker that window is 7 seconds. The strategies were stopped only from
worker_exit, one host after the other. Under gthread they are now told to stop
as soon as the worker is, beside the open requests and beside each other.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from test_gthread_deploy_broker_smoke import FakeOpenAlgo, smoke

ROOT = Path(__file__).resolve().parents[1]

on_linux_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the switch script is a bash script for Linux servers",
)


# ---------------------------------------------------------------------------
# switch-worker.sh --restore
# ---------------------------------------------------------------------------


@pytest.fixture
def box(tmp_path):
    from test_gthread_deploy_switch_worker import Box

    return Box(tmp_path)


@on_linux_bash
def test_restore_sets_env_back_so_the_next_update_does_not_switch_again(box):
    unit = box.single(env_text="APP_KEY = 'x'\n")
    original = unit.read_bytes()
    env_file = box.root / "openalgo" / ".env"

    switched = box.run("--to", "gthread", "--yes")
    assert switched.returncode == 0, switched.stdout + switched.stderr
    assert "OPENALGO_WORKER_CLASS = 'gthread'" in env_file.read_text()

    restored = box.run("--restore", "--yes")
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert unit.read_bytes() == original
    assert "OPENALGO_WORKER_CLASS = 'eventlet'" in env_file.read_text()
    assert "OPENALGO_WORKER_CLASS = 'gthread'" not in env_file.read_text()

    # What update.sh asks next: 3 means there is nothing to switch.
    assert box.run("--check", "--service", "openalgo").returncode == 3


@on_linux_bash
def test_restore_leaves_an_env_that_never_asked_for_gthread_alone(box):
    box.single(env_text="APP_KEY = 'x'\n")
    env_file = box.root / "openalgo" / ".env"
    assert box.run("--yes").returncode == 0  # switched onto the launcher only
    before = env_file.read_bytes()

    restored = box.run("--restore", "--yes")

    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert env_file.read_bytes() == before


@on_linux_bash
def test_a_dry_run_restore_says_it_would_set_env_back(box):
    box.single()  # .env asks for gthread
    env_file = box.root / "openalgo" / ".env"
    assert box.run("--yes").returncode == 0
    before = env_file.read_bytes()

    dry = box.run("--restore", "--dry-run")

    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "Would set OPENALGO_WORKER_CLASS = 'eventlet'" in dry.stdout
    assert env_file.read_bytes() == before


# ---------------------------------------------------------------------------
# scripts/gthread_broker_smoke.py --order-check
# ---------------------------------------------------------------------------


@pytest.fixture
def fake():
    server = FakeOpenAlgo()
    yield server
    server.close()


@pytest.mark.parametrize(
    ("exchange", "product"), [("NSE", "CNC"), ("BSE", "CNC"), ("NFO", "NRML"), ("MCX", "NRML")]
)
def test_the_order_check_never_uses_mis(fake, capsys, exchange, product):
    fake.analyze = True
    status = smoke.main(
        ["--url", fake.url, "--apikey", "k", "--order-check", "--exchange", exchange]
    )
    capsys.readouterr()
    assert status == 0
    order = next(body for endpoint, body in fake.calls if endpoint == "placeorder")
    assert order["product"] == product


def test_an_order_answered_without_a_sandbox_mode_is_reported_as_live(fake, capsys):
    """A live /placeorder success is {"status": "success", "orderid": ...}, no mode."""
    fake.analyze = True
    sandbox_answer = fake.answer

    def answer(endpoint, body):
        if endpoint == "placeorder":
            return 200, {"status": "success", "orderid": "LIVE1"}
        if endpoint == "cancelorder":
            return 500, {"status": "error", "message": "Broker is busy"}
        return sandbox_answer(endpoint, body)

    fake.answer = answer
    status = smoke.main(["--url", fake.url, "--apikey", "k", "--order-check"])
    out = capsys.readouterr().out

    assert status == 1
    assert "the order reached live mode" in out
    assert "cancel order LIVE1 in your broker's order book now" in out


# ---------------------------------------------------------------------------
# install/lib/resolve_runtime.py thread_limit_warnings
# ---------------------------------------------------------------------------


def _resolver():
    spec = importlib.util.spec_from_file_location(
        "resolve_runtime_under_review", ROOT / "install" / "lib" / "resolve_runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cgroup_tree(tmp_path, proc_line, limits):
    root = tmp_path / "cgroup"
    for rel, value in limits.items():
        folder = root / rel if rel else root
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pids.max").write_text(f"{value}\n", encoding="ascii")
    root.mkdir(parents=True, exist_ok=True)
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text(proc_line + "\n", encoding="ascii")
    return str(proc), str(root)


def test_a_systemd_services_tasksmax_is_found_in_its_own_cgroup(tmp_path):
    resolver = _resolver()
    proc, root = _cgroup_tree(
        tmp_path,
        "0::/system.slice/openalgo.service",
        {os.path.join("system.slice", "openalgo.service"): 200},
    )

    notes = resolver.thread_limit_warnings(64, proc_cgroup=proc, cgroup_root=root)

    assert any("at most 200 tasks" in note and "TasksMax" in note for note in notes), notes


def test_a_slice_limit_above_the_service_counts_too(tmp_path):
    resolver = _resolver()
    proc, root = _cgroup_tree(
        tmp_path,
        "0::/system.slice/openalgo.service",
        {
            os.path.join("system.slice", "openalgo.service"): "max",
            "system.slice": 150,
        },
    )

    notes = resolver.thread_limit_warnings(64, proc_cgroup=proc, cgroup_root=root)

    assert any("at most 150 tasks" in note for note in notes), notes


def test_a_generous_or_absent_limit_warns_nothing(tmp_path):
    resolver = _resolver()
    proc, root = _cgroup_tree(
        tmp_path,
        "0::/system.slice/openalgo.service",
        {os.path.join("system.slice", "openalgo.service"): 23989},
    )
    assert [
        n
        for n in resolver.thread_limit_warnings(64, proc_cgroup=proc, cgroup_root=root)
        if "tasks" in n
    ] == []
    empty_proc, empty_root = _cgroup_tree(tmp_path / "none", "0::/", {})
    assert [
        n
        for n in resolver.thread_limit_warnings(64, proc_cgroup=empty_proc, cgroup_root=empty_root)
        if "tasks" in n
    ] == []


def test_a_container_limit_at_the_root_is_still_found(tmp_path):
    resolver = _resolver()
    proc, root = _cgroup_tree(tmp_path, "0::/", {"": 100})

    notes = resolver.thread_limit_warnings(64, proc_cgroup=proc, cgroup_root=root)

    assert any("at most 100 tasks" in note for note in notes), notes


def test_cgroup_v1_pids_controller_is_read(tmp_path):
    resolver = _resolver()
    proc, root = _cgroup_tree(
        tmp_path,
        "4:pids:/system.slice/openalgo.service",
        {os.path.join("pids", "system.slice", "openalgo.service"): 120},
    )

    notes = resolver.thread_limit_warnings(64, proc_cgroup=proc, cgroup_root=root)

    assert any("at most 120 tasks" in note for note in notes), notes


# ---------------------------------------------------------------------------
# Early shutdown hooks start at the stop signal, side by side
# ---------------------------------------------------------------------------


@pytest.fixture
def quiet_shutdown(monkeypatch):
    from utils import shutdown

    calls = []
    monkeypatch.setattr(shutdown, "_shutdown_done", False)
    monkeypatch.setattr(shutdown, "_hooks", [])
    monkeypatch.setattr(shutdown, "_early_started", None)
    monkeypatch.setattr(shutdown, "_signal_streams_to_stop", lambda: None)
    for name in (
        "_stop_health_collector",
        "_stop_flow_scheduler",
        "_stop_historify_scheduler",
        "_stop_chartink_scheduler",
        "_stop_python_strategy_scheduler",
        "_stop_squareoff_scheduler",
        "_stop_strategy_module",
        "_stop_websocket_proxy",
        "_remove_all_scoped_sessions",
    ):
        monkeypatch.setattr(shutdown, name, lambda n=name: calls.append(n))
    yield shutdown
    shutdown._shutdown_done = False


def test_early_hooks_start_at_once_and_side_by_side(quiet_shutdown):
    shutdown = quiet_shutdown
    started = {}
    release = threading.Event()

    def hook(name):
        def run():
            started[name] = time.monotonic()
            release.wait(5)

        return run

    shutdown.register_shutdown_hook(hook("strategies"), name="strategies", early=True)
    shutdown.register_shutdown_hook(hook("openscript"), name="openscript", early=True)

    began = time.monotonic()
    assert shutdown.begin_early_shutdown() is True
    assert shutdown.begin_early_shutdown() is False  # idempotent
    assert time.monotonic() - began < 0.5, "begin_early_shutdown waited for the hooks"
    deadline = time.monotonic() + 5
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert set(started) == {"strategies", "openscript"}, "the hooks ran one after the other"
    release.set()


def test_shutdown_runtime_waits_for_hooks_already_started_and_does_not_rerun_them(
    quiet_shutdown,
):
    shutdown = quiet_shutdown
    runs = []
    finished = threading.Event()

    def strategies():
        runs.append("strategies")
        time.sleep(0.3)
        finished.set()

    shutdown.register_shutdown_hook(strategies, name="strategies", early=True)
    assert shutdown.begin_early_shutdown() is True

    shutdown.shutdown_runtime()

    assert finished.is_set(), "shutdown_runtime did not wait for the running hook"
    assert runs == ["strategies"]


def test_without_an_early_start_shutdown_runtime_runs_them_as_before(quiet_shutdown):
    shutdown = quiet_shutdown
    runs = []
    shutdown.register_shutdown_hook(lambda: runs.append("strategies"), name="s", early=True)

    shutdown.shutdown_runtime()

    assert runs == ["strategies"]
    assert shutdown.begin_early_shutdown() is False  # shutdown already ran


def _hooks_module():
    spec = importlib.util.spec_from_file_location(
        "gunicorn_hooks_under_review", ROOT / "install" / "lib" / "gunicorn_hooks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Log:
    def info(self, message):
        pass

    def warning(self, message):
        pass


@pytest.mark.parametrize("gthread", [True, False])
def test_the_stop_drain_starts_the_early_hooks_under_gthread_only(monkeypatch, gthread):
    from utils import runtime, shutdown

    hooks = _hooks_module()
    calls = []
    monkeypatch.setattr(runtime, "gthread_active", lambda: gthread)
    monkeypatch.setattr(shutdown, "begin_early_shutdown", lambda: calls.append("early") or True)
    worker = type("W", (), {"log": _Log(), "wsgi": None})()

    hooks._drain_connections(worker)

    assert calls == (["early"] if gthread else [])
