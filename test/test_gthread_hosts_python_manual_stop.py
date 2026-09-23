"""A manual Stop wins against a scheduled start already past its check (hosts-03).

scheduled_start_strategy read ``manually_stopped``, then did calendar and
database work, then started the strategy; start_strategy_process never read the
flag again. The stop route decided on the config's ``is_running`` flag with no
lock held, and when that said False it only recorded the manual stop and
answered "Scheduled auto-start cancelled". At the cron minute the two
interleave: the trader is told the start is cancelled and the strategy starts.

Now the stop route records the flag and decides whether anything is running in
one hold of PROCESS_LOCK, and every automatic start reads the flag again under
the same lock before it spawns.

The first test parks a scheduled start after its manually_stopped check, runs
the stop route to completion, then lets the start go on. On the old code the
strategy is spawned and registered.
"""

import threading

import pytest
from flask import Flask, session

from blueprints import python_strategy as ps


class FakeProcess:
    """What a spawn hands back, without spawning anything."""

    next_pid = 71000

    def __init__(self, *args, **kwargs):
        FakeProcess.next_pid += 1
        self.pid = FakeProcess.next_pid
        self.returncode = None

    def poll(self):
        return self.returncode


@pytest.fixture
def host(monkeypatch, tmp_path):
    saved_configs = dict(ps.STRATEGY_CONFIGS)
    saved_running = dict(ps.RUNNING_STRATEGIES)
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()

    script = tmp_path / "turtle.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    ps.STRATEGY_CONFIGS["turtle"] = {
        "name": "Turtle",
        "file_path": str(script),
        "user_id": "trader",
        "exchange": "NSE",
        "is_running": False,
        "is_scheduled": True,
        "schedule_days": [],
    }

    spawned = []

    def fake_popen(*args, **kwargs):
        process = FakeProcess()
        spawned.append(process)
        return process

    monkeypatch.setattr(ps.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda *a, **k: (True, "ready"))
    monkeypatch.setattr(ps, "save_configs", lambda: True)
    monkeypatch.setattr(ps, "broadcast_status_update", lambda *a, **k: None)
    monkeypatch.setattr(ps, "LOGS_DIR", tmp_path)

    app = Flask(__name__)
    app.secret_key = "test"
    yield app, spawned

    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(saved_configs)
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(saved_running)


def _press_stop(app, strategy_id):
    with app.test_request_context(f"/python/stop/{strategy_id}", method="POST"):
        session["user"] = "trader"
        response = ps.stop_strategy.__wrapped__(strategy_id)
        if isinstance(response, tuple):
            response = response[0]
        return response.get_json()


def test_a_stop_pressed_during_a_scheduled_start_is_honoured(host, monkeypatch):
    app, spawned = host
    parked = threading.Event()
    release = threading.Event()

    def slow_market_status(exchange):
        # The scheduled start has read manually_stopped (False) and is now in
        # its calendar check, which is where the trader's Stop lands.
        parked.set()
        release.wait(5)
        return {"is_trading": True, "reason": None, "message": "open"}

    monkeypatch.setattr(ps, "get_market_status", slow_market_status)

    scheduled = threading.Thread(target=ps.scheduled_start_strategy, args=("turtle",))
    scheduled.start()
    assert parked.wait(5)

    answer = _press_stop(app, "turtle")
    assert answer["status"] == "success"
    assert answer["message"] == "Scheduled auto-start cancelled"

    release.set()
    scheduled.join(5)

    assert spawned == [], "the strategy was started after the trader was told it would not be"
    assert "turtle" not in ps.RUNNING_STRATEGIES
    assert ps.STRATEGY_CONFIGS["turtle"]["manually_stopped"] is True


def test_the_enforcer_does_not_resume_a_strategy_stopped_mid_pass(host, monkeypatch):
    """The per-minute enforcer re-reads the flag under the lock before it starts."""
    app, spawned = host
    config = ps.STRATEGY_CONFIGS["turtle"]
    config["paused_reason"] = "holiday"

    parked = threading.Event()
    release = threading.Event()

    def within_window(strategy_id):
        parked.set()
        release.wait(5)
        return True

    monkeypatch.setattr(
        ps, "get_market_status", lambda exch: {"is_trading": True, "reason": None, "message": ""}
    )
    monkeypatch.setattr(ps, "is_within_schedule_time", within_window)
    monkeypatch.setattr(ps, "_is_strategy_running", lambda sid, cfg: False)

    enforcer = threading.Thread(target=ps.market_hours_enforcer)
    enforcer.start()
    assert parked.wait(5)
    assert _press_stop(app, "turtle")["status"] == "success"
    release.set()
    enforcer.join(5)

    assert spawned == []
    assert "turtle" not in ps.RUNNING_STRATEGIES


def test_stop_stops_a_tracked_strategy_whose_config_says_stopped(host, monkeypatch):
    """The stop route asks the registry, not only the config flag.

    A config wrongly left at is_running=False (the concurrent restore defect,
    hosts-04) made Stop only record a manual stop and leave the process trading.
    """
    app, _ = host
    stopped = []

    def fake_stop(strategy_id):
        stopped.append(strategy_id)
        with ps.PROCESS_LOCK:
            ps.RUNNING_STRATEGIES.pop(strategy_id, None)
        return True, "Strategy stopped"

    monkeypatch.setattr(ps, "stop_strategy_process", fake_stop)
    ps.RUNNING_STRATEGIES["turtle"] = {"process": FakeProcess(), "pid": 1, "log_file": None}

    answer = _press_stop(app, "turtle")

    assert stopped == ["turtle"]
    assert answer == {"status": "success", "message": "Strategy stopped"}
    assert ps.STRATEGY_CONFIGS["turtle"]["manually_stopped"] is True


def test_a_failed_stop_leaves_the_manual_stop_as_it_was(host, monkeypatch):
    """Nothing was stopped, so nothing is recorded, as before."""
    app, _ = host
    ps.STRATEGY_CONFIGS["turtle"]["is_running"] = True
    monkeypatch.setattr(ps, "stop_strategy_process", lambda sid: (False, "Strategy not running"))

    answer = _press_stop(app, "turtle")

    assert answer == {"status": "error", "message": "Strategy not running"}
    assert "manually_stopped" not in ps.STRATEGY_CONFIGS["turtle"]
