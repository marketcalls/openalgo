"""Recovery contract tests for the isolated Python strategy host."""

from datetime import datetime

import pytz

from blueprints import python_strategy as ps

IST = pytz.timezone("Asia/Kolkata")


def _at(year=2026, month=10, day=28, hour=10, minute=3):
    return IST.localize(datetime(year, month, day, hour, minute))


def test_same_day_interrupted_run_is_resumed_inside_schedule(monkeypatch):
    config = {
        "last_started": _at(hour=9).isoformat(),
        "restart_policy": "resume",
        "is_scheduled": True,
    }
    monkeypatch.setattr(ps, "is_within_schedule_time", lambda strategy_id: True)
    action, reason = ps.restart_recovery_decision("trend", config, now=_at())
    assert action == "resume"
    assert "same-day" in reason


def test_previous_day_run_is_never_automatically_resurrected(monkeypatch):
    config = {
        "last_started": _at(day=27, hour=9).isoformat(),
        "restart_policy": "resume",
        "is_scheduled": True,
    }
    monkeypatch.setattr(ps, "is_within_schedule_time", lambda strategy_id: True)
    action, reason = ps.restart_recovery_decision("trend", config, now=_at())
    assert action == "close"
    assert "earlier trading date" in reason


def test_scheduled_run_is_not_resumed_outside_its_window(monkeypatch):
    config = {
        "last_started": _at(hour=9).isoformat(),
        "restart_policy": "resume",
        "is_scheduled": True,
    }
    monkeypatch.setattr(ps, "is_within_schedule_time", lambda strategy_id: False)
    action, reason = ps.restart_recovery_decision("trend", config, now=_at(hour=16))
    assert action == "close"
    assert "outside" in reason


def test_scheduled_run_is_not_resumed_on_an_unselected_day(monkeypatch):
    config = {
        "last_started": _at(hour=9).isoformat(),
        "restart_policy": "resume",
        "is_scheduled": True,
        "schedule_days": ["tue"],
    }
    monkeypatch.setattr(ps, "is_within_schedule_time", lambda strategy_id: True)
    action, reason = ps.restart_recovery_decision("trend", config, now=_at())
    assert action == "close"
    assert "not scheduled" in reason


def test_manual_policy_requires_recovery_without_starting():
    config = {"last_started": _at(hour=9).isoformat(), "restart_policy": "manual"}
    action, reason = ps.restart_recovery_decision("trend", config, now=_at())
    assert action == "manual"
    assert "confirmation" in reason


def test_cleanup_preserves_running_intent_for_next_process(monkeypatch):
    saved_configs = ps.STRATEGY_CONFIGS
    saved_running = ps.RUNNING_STRATEGIES
    saved_shutting_down = ps._SHUTTING_DOWN.is_set()
    saved_keep_records = ps._SHUTDOWN_KEEPS_RECORDS.is_set()
    try:
        ps.STRATEGY_CONFIGS = {"trend": {"is_running": True, "pid": 123}}
        ps.RUNNING_STRATEGIES = {"trend": {"pid": 123, "process": object()}}
        calls = []
        monkeypatch.setattr(ps, "save_configs", lambda: True)
        monkeypatch.setattr(
            ps,
            "stop_strategy_process",
            lambda strategy_id, keep_record=False: (
                calls.append((strategy_id, keep_record)) or (True, "stopped")
            ),
        )
        ps._SHUTDOWN_KEEPS_RECORDS.set()
        ps.cleanup_on_exit()
        assert calls == [("trend", True)]
        config = ps.STRATEGY_CONFIGS["trend"]
        assert config["is_running"] is True
        assert config["lifecycle_state"] == "recovery_pending"
    finally:
        ps.STRATEGY_CONFIGS = saved_configs
        ps.RUNNING_STRATEGIES = saved_running
        if not saved_shutting_down:
            ps._SHUTTING_DOWN.clear()
        if not saved_keep_records:
            ps._SHUTDOWN_KEEPS_RECORDS.clear()


def test_closed_recovery_record_is_persisted(monkeypatch):
    config = {
        "is_running": True,
        "pid": 123,
        "last_started": _at(day=27, hour=9).isoformat(),
        "restart_policy": "resume",
    }
    saves = []
    monkeypatch.setattr(ps, "snapshot_strategy_configs", lambda: [("trend", config)])
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda **_kwargs: (True, "ready"))
    monkeypatch.setattr(ps, "restore_running_strategy_process", lambda *_args: False)
    monkeypatch.setattr(ps, "save_configs", lambda: saves.append(True) or True)
    monkeypatch.setattr(ps, "get_ist_time", lambda: _at())

    ps._restore_strategy_states_locked()

    assert config["is_running"] is False
    assert config["pid"] is None
    assert saves == [True]


def test_record_recovery_required_is_visible_and_non_running():
    config = {"is_running": True, "pid": 123}
    ps._record_recovery_required(config, "broker state needs review")
    assert config["is_running"] is False
    assert config["lifecycle_state"] == "recovery_required"
    assert config["recovery_required"] is True
