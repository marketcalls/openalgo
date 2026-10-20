"""A delete cannot remove the config of a strategy that starts during it (hosts-05).

delete_strategy stops the process outside PROCESS_LOCK, then takes the lock and
removes the config, the schedule and the file without asking again whether
anything is running. A scheduled start, the enforcer or another tab landing in
that gap spawned the strategy, and the delete then removed everything that
could have stopped it: a strategy trading with no row, no scheduled stop and no
route to stop it.

Now the delete claims the strategy first, a start is refused while the claim
stands, and the final step checks again. The test starts the strategy in the
gap. On the old code the process is registered and its config is gone.
"""

import threading

import pytest
from flask import Flask, session

from blueprints import python_strategy as ps


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.pid = 2_000_100_000

    def poll(self):
        return None


@pytest.fixture
def host(monkeypatch, tmp_path):
    saved_configs = dict(ps.STRATEGY_CONFIGS)
    saved_running = dict(ps.RUNNING_STRATEGIES)
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()

    script = tmp_path / "gap.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    ps.STRATEGY_CONFIGS["gap"] = {
        "name": "Gap",
        "file_path": str(script),
        "user_id": "trader",
        "exchange": "NSE",
        "is_running": True,
        "is_scheduled": False,
    }
    ps.RUNNING_STRATEGIES["gap"] = {"process": FakeProcess(), "pid": 1, "log_file": None}

    monkeypatch.setattr(ps.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda *a, **k: (True, "ready"))
    monkeypatch.setattr(ps, "save_configs", lambda: True)
    monkeypatch.setattr(ps, "broadcast_status_update", lambda *a, **k: None)
    monkeypatch.setattr(ps, "LOGS_DIR", tmp_path)

    app = Flask(__name__)
    app.secret_key = "test"
    yield app

    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(saved_configs)
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(saved_running)


def _press_delete(app, strategy_id):
    with app.test_request_context(f"/python/delete/{strategy_id}", method="POST"):
        session["user"] = "trader"
        response = ps.delete_strategy.__wrapped__(strategy_id)
        code = 200
        if isinstance(response, tuple):
            response, code = response
        return code, response.get_json()


def test_a_start_in_the_gap_after_the_stop_cannot_orphan_a_process(host, monkeypatch):
    app = host
    stopped = threading.Event()
    start_done = threading.Event()
    start_result = {}

    def stop_then_pause(strategy_id):
        with ps.PROCESS_LOCK:
            ps.RUNNING_STRATEGIES.pop(strategy_id, None)
            ps.STRATEGY_CONFIGS[strategy_id]["is_running"] = False
        stopped.set()
        # The gap between the stop returning and the delete taking the lock.
        start_done.wait(5)
        return True, "Strategy stopped"

    monkeypatch.setattr(ps, "stop_strategy_process", stop_then_pause)

    def start_in_gap():
        stopped.wait(5)
        start_result["value"] = ps.start_strategy_process("gap")
        start_done.set()

    starter = threading.Thread(target=start_in_gap)
    starter.start()
    code, body = _press_delete(app, "gap")
    starter.join(5)

    orphaned = [sid for sid in ps.RUNNING_STRATEGIES if sid not in ps.STRATEGY_CONFIGS]
    assert orphaned == [], "a process is running with no config left to stop it"
    # With the claim the start is refused and the delete goes through.
    assert start_result["value"] == (False, ps.DELETING_MESSAGE)
    assert code == 200 and body["status"] == "success"
    assert "gap" not in ps.STRATEGY_CONFIGS


def test_a_second_delete_of_the_same_strategy_is_refused(host, monkeypatch):
    app = host
    in_stop = threading.Event()
    release = threading.Event()

    def slow_stop(strategy_id):
        in_stop.set()
        release.wait(5)
        with ps.PROCESS_LOCK:
            ps.RUNNING_STRATEGIES.pop(strategy_id, None)
        return True, "Strategy stopped"

    monkeypatch.setattr(ps, "stop_strategy_process", slow_stop)

    first = {}
    worker = threading.Thread(target=lambda: first.update(result=_press_delete(app, "gap")))
    worker.start()
    assert in_stop.wait(5)

    code, body = _press_delete(app, "gap")
    release.set()
    worker.join(5)

    assert code == 409
    assert body["message"] == "This strategy is already being deleted."
    assert first["result"][0] == 200
    assert ps.DELETING_STRATEGIES == set()


def test_the_claim_is_released_when_a_delete_is_refused(host, monkeypatch):
    app = host
    monkeypatch.setattr(ps, "stop_strategy_process", lambda sid: (False, "Failed to stop"))
    monkeypatch.setattr(ps, "_strategy_may_still_be_running", lambda sid: True)

    code, _ = _press_delete(app, "gap")

    assert code == 409
    assert "gap" not in ps.DELETING_STRATEGIES
    assert "gap" in ps.STRATEGY_CONFIGS
