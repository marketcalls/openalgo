"""Restore passes run one at a time and never mark a live strategy failed (hosts-04).

restore_strategy_states runs from the startup thread, from every login's master
contract hook and from requests, with no lock between them. Two passes both saw
a strategy as down: one restarted it, the other's start was refused with
"Strategy already running", and its failure branch then wrote is_running=False
and an error over the strategy the first had just started. The page showed an
error while the strategy traded, and Stop only recorded a manual stop.

initialize_with_app_context set its flag before doing the work and without a
lock, so a second caller went on against half-restored state.

The first test runs two restore passes together against a strategy whose
recorded process is gone. On the old code one of them marks the running
strategy as failed.
"""

import threading
import time

import pytest

from blueprints import python_strategy as ps


class SlowProcess:
    """A spawned strategy that took a moment to launch."""

    next_pid = 2_000_000_000

    def __init__(self, *args, **kwargs):
        time.sleep(0.2)
        SlowProcess.next_pid += 1
        self.pid = SlowProcess.next_pid

    def poll(self):
        return None


@pytest.fixture
def host(monkeypatch, tmp_path):
    saved_configs = dict(ps.STRATEGY_CONFIGS)
    saved_running = dict(ps.RUNNING_STRATEGIES)
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()

    script = tmp_path / "trend.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    ps.STRATEGY_CONFIGS["trend"] = {
        "name": "Trend",
        "file_path": str(script),
        "exchange": "NSE",
        "is_running": True,
        # A process id that does not exist: the previous worker's child is gone.
        "pid": 2_147_000_000,
    }

    spawned = []

    def popen(*args, **kwargs):
        process = SlowProcess()
        spawned.append(process)
        return process

    monkeypatch.setattr(ps.subprocess, "Popen", popen)
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda *a, **k: (True, "ready"))
    monkeypatch.setattr(ps, "save_configs", lambda: True)
    monkeypatch.setattr(ps, "broadcast_status_update", lambda *a, **k: None)
    monkeypatch.setattr(ps, "LOGS_DIR", tmp_path)
    yield spawned

    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(saved_configs)
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(saved_running)


def test_two_restore_passes_start_once_and_leave_it_running(host):
    spawned = host
    barrier = threading.Barrier(2)

    def restore():
        barrier.wait()
        ps.restore_strategy_states()

    threads = [threading.Thread(target=restore) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    config = ps.STRATEGY_CONFIGS["trend"]
    assert len(spawned) == 1
    assert "trend" in ps.RUNNING_STRATEGIES
    assert config["is_running"] is True, config
    assert "is_error" not in config, config
    assert config["pid"] == spawned[0].pid


def test_login_restore_and_the_contracts_route_start_a_waiting_strategy_once(host):
    """Pending starts are single flight too: two callers, one spawn."""
    spawned = host
    config = ps.STRATEGY_CONFIGS["trend"]
    config.update(
        {
            "is_running": False,
            "pid": None,
            "is_error": True,
            "error_message": "Waiting for master contracts to be downloaded",
        }
    )
    barrier = threading.Barrier(2)
    results = []

    def pending():
        barrier.wait()
        results.append(ps.check_and_start_pending_strategies())

    threads = [threading.Thread(target=pending) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(spawned) == 1
    assert sorted(started for _, started, _ in results) == [0, 1]


def test_initialisation_runs_once_and_is_marked_done_last(monkeypatch):
    runs = []
    seen_flag = []

    def slow_restore():
        seen_flag.append(ps._initialized)
        runs.append(1)
        time.sleep(0.2)

    monkeypatch.setattr(ps, "_initialized", False)
    monkeypatch.setattr(ps, "restore_strategy_states", slow_restore)
    monkeypatch.setattr(ps, "daily_trading_day_check", lambda: None)
    monkeypatch.setattr(ps, "snapshot_strategy_configs", lambda: [])

    barrier = threading.Barrier(8)
    returned_before_done = []

    def init():
        barrier.wait()
        ps.initialize_with_app_context()
        if not runs or not ps._initialized:
            returned_before_done.append(1)

    threads = [threading.Thread(target=init) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(runs) == 1
    assert seen_flag == [False], "the flag was set before the work was done"
    assert returned_before_done == [], "a caller went on before initialisation finished"
    assert ps._initialized is True


def test_a_failed_initialisation_is_retried(monkeypatch):
    attempts = []

    def failing_restore():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("no app context yet")

    monkeypatch.setattr(ps, "_initialized", False)
    monkeypatch.setattr(ps, "restore_strategy_states", failing_restore)
    monkeypatch.setattr(ps, "daily_trading_day_check", lambda: None)
    monkeypatch.setattr(ps, "snapshot_strategy_configs", lambda: [])

    ps.initialize_with_app_context()
    assert ps._initialized is False
    ps.initialize_with_app_context()
    assert ps._initialized is True
    assert len(attempts) == 2
