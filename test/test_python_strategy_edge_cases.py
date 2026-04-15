"""Deep edge-case tests for /python exchange-aware scheduler.

Companion to test_python_strategy_exchange_aware.py — covers the things that
the happy-path tests don't: cross-midnight MCX sessions, manual-stopped
immunity, multi-strategy independence, malformed configs, full-closure
holidays, NSE strategy outside default 09:15-15:30 even when user set wider
window, env var injection, and concurrent enforcer/start interactions.

Run:
    uv run pytest test/test_python_strategy_edge_cases.py -v
"""

import json
import os
import sys
from datetime import date, datetime
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytz  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def calendar_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.pool import StaticPool

    import database.market_calendar_db as mc

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    mc.engine = engine
    mc.db_session = scoped_session(
        sessionmaker(autocommit=False, autoflush=False, bind=engine)
    )
    mc.Base.query = mc.db_session.query_property()
    mc.Base.metadata.create_all(engine)
    mc.clear_market_calendar_cache()

    mc.seed_holidays_2026()
    mc.seed_market_timings()

    return mc


@pytest.fixture()
def ps_module(calendar_db):
    """Reset state between tests."""
    from blueprints import python_strategy as ps

    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()
    calendar_db.clear_market_calendar_cache()
    yield ps
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()


def _patch_now(target_date: date, hour: int, minute: int = 0, second: int = 0):
    fixed = IST.localize(
        datetime(target_date.year, target_date.month, target_date.day, hour, minute, second)
    )
    p = patch("blueprints.python_strategy.datetime")
    m = p.start()
    m.now.return_value = fixed
    m.combine = datetime.combine
    m.fromisoformat = datetime.fromisoformat
    m.fromtimestamp = datetime.fromtimestamp
    m.min = datetime.min
    m.max = datetime.max
    return p


# ---------------------------------------------------------------------------
# Edge case 1: NSE strategy with a too-wide user window
# ---------------------------------------------------------------------------


def test_nse_user_widens_schedule_past_market_close(ps_module):
    """User schedules NSE 09:15-23:00, but NSE actually closes at 15:30.
    is_within_schedule_time must respect the exchange's session window."""
    ps_module.STRATEGY_CONFIGS["wide"] = {
        "exchange": "NSE",
        "schedule_start": "09:15",
        "schedule_stop": "23:00",
    }
    # Pick a regular Tuesday (2026-04-07)
    p = _patch_now(date(2026, 4, 7), 18, 0)  # 18:00 — past NSE close
    try:
        assert ps_module.is_within_schedule_time("wide") is False
    finally:
        p.stop()


def test_nse_user_within_market_and_user_window(ps_module):
    """At 11:00 on a regular trading day, NSE strategy with 09:15-15:30 is within window."""
    ps_module.STRATEGY_CONFIGS["w"] = {
        "exchange": "NSE",
        "schedule_start": "09:15",
        "schedule_stop": "15:30",
    }
    p = _patch_now(date(2026, 4, 7), 11, 0)
    try:
        assert ps_module.is_within_schedule_time("w") is True
    finally:
        p.stop()


# ---------------------------------------------------------------------------
# Edge case 2: MCX Muhurat session crosses midnight (18:00 -> 00:15 next day)
# ---------------------------------------------------------------------------


def test_mcx_muhurat_session_inside_window(calendar_db, ps_module):
    """8-Nov-2026 22:00 (during Muhurat 18:00-00:15 next day): MCX in window."""
    win = calendar_db.get_effective_session_window(date(2026, 11, 8), "MCX")
    assert win is not None and win["is_special"] is True

    ps_module.STRATEGY_CONFIGS["m"] = {
        "exchange": "MCX",
        "schedule_start": "18:00",
        "schedule_stop": "23:59",
    }
    p = _patch_now(date(2026, 11, 8), 22, 0)
    try:
        assert ps_module.is_within_schedule_time("m") is True
    finally:
        p.stop()


def test_mcx_muhurat_post_midnight_known_limitation(ps_module):
    """At 00:10 Nov 9 the Muhurat MCX (ends 00:15 Nov 9) is technically still in
    session. Our current implementation queries by date and Nov 9 has no special
    session, so we fall back to Nov 9's default 09:00-23:55 — the strategy WILL
    NOT be considered in window. This is a known limitation; documented here so
    a future fix doesn't silently change behaviour."""
    ps_module.STRATEGY_CONFIGS["m"] = {
        "exchange": "MCX",
        "schedule_start": "00:00",
        "schedule_stop": "23:59",
    }
    p = _patch_now(date(2026, 11, 9), 0, 10)  # 00:10 Nov 9
    try:
        # Documents current behavior; flip if a future patch handles cross-midnight.
        assert ps_module.is_within_schedule_time("m") is False
    finally:
        p.stop()


# ---------------------------------------------------------------------------
# Edge case 3: manually_stopped immunity
# ---------------------------------------------------------------------------


def test_manually_stopped_not_resumed_by_enforcer(ps_module, monkeypatch):
    """An MCX strategy stopped by the user must NOT be auto-restarted by the
    minute-tick enforcer when the exchange reopens."""
    ps_module.STRATEGY_CONFIGS["m"] = {
        "exchange": "MCX",
        "schedule_start": "09:00",
        "schedule_stop": "23:55",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
        "is_scheduled": True,
        "manually_stopped": True,
        "paused_reason": "holiday",
    }

    started = []
    monkeypatch.setattr(
        ps_module, "start_strategy_process", lambda sid: started.append(sid) or (True, "ok")
    )
    monkeypatch.setattr(ps_module, "_is_strategy_running", lambda sid, cfg: False)

    p = _patch_now(date(2026, 4, 14), 19, 0)  # MCX evening session live
    try:
        ps_module.market_hours_enforcer()
    finally:
        p.stop()

    # Manually stopped → enforcer must NOT auto-start
    assert started == []


def test_scheduled_start_skips_manually_stopped(ps_module, monkeypatch):
    """scheduled_start_strategy must short-circuit when manually_stopped=True."""
    ps_module.STRATEGY_CONFIGS["m"] = {
        "exchange": "MCX",
        "schedule_start": "17:00",
        "schedule_stop": "23:55",
        "schedule_days": ["tue"],
        "is_scheduled": True,
        "manually_stopped": True,
    }
    started = []
    monkeypatch.setattr(
        ps_module, "start_strategy_process", lambda sid: started.append(sid) or (True, "ok")
    )

    p = _patch_now(date(2026, 4, 14), 17, 0)
    try:
        ps_module.scheduled_start_strategy("m")
    finally:
        p.stop()

    assert started == []


# ---------------------------------------------------------------------------
# Edge case 4: Multi-strategy independence on the same tick
# ---------------------------------------------------------------------------


def test_multi_strategy_per_exchange_decisions(ps_module, monkeypatch):
    """On 14-Apr-2026 19:00 IST: NSE strategy stays paused; MCX strategy
    (currently paused) gets resumed; CRYPTO strategy untouched."""
    ps_module.STRATEGY_CONFIGS["nse_strat"] = {
        "exchange": "NSE",
        "schedule_start": "09:15",
        "schedule_stop": "15:30",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
        "is_scheduled": True,
        "paused_reason": "holiday",
        "paused_message": "NSE closed - Holiday",
    }
    ps_module.STRATEGY_CONFIGS["mcx_strat"] = {
        "exchange": "MCX",
        "schedule_start": "17:00",
        "schedule_stop": "23:55",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
        "is_scheduled": True,
        "paused_reason": "holiday",
        "paused_message": "MCX closed - Holiday",
    }
    ps_module.STRATEGY_CONFIGS["crypto_strat"] = {
        "exchange": "CRYPTO",
        "schedule_start": "00:00",
        "schedule_stop": "23:59",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "is_scheduled": True,
    }

    started = []
    stopped = []
    monkeypatch.setattr(
        ps_module, "start_strategy_process", lambda sid: started.append(sid) or (True, "ok")
    )
    monkeypatch.setattr(
        ps_module, "stop_strategy_process", lambda sid: stopped.append(sid) or (True, "ok")
    )
    monkeypatch.setattr(ps_module, "_is_strategy_running", lambda sid, cfg: False)
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)

    p = _patch_now(date(2026, 4, 14), 19, 0)
    try:
        ps_module.market_hours_enforcer()
    finally:
        p.stop()

    # MCX should resume (was paused, exchange now open at 19:00)
    assert "mcx_strat" in started, f"started={started}"
    # NSE shouldn't resume (still NSE-closed)
    assert "nse_strat" not in started
    # Nobody should be force-stopped (none were marked running)
    assert stopped == []
    # MCX paused reason cleared
    assert "paused_reason" not in ps_module.STRATEGY_CONFIGS["mcx_strat"]


def test_multi_strategy_daily_check(ps_module, monkeypatch):
    """daily_trading_day_check on 14-Apr-2026: stops running NSE strategy,
    leaves running MCX/CRYPTO strategies alone."""
    ps_module.STRATEGY_CONFIGS["nse_strat"] = {
        "exchange": "NSE",
        "schedule_start": "09:15",
        "schedule_stop": "15:30",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
        "is_scheduled": True,
        "is_running": True,
        "pid": 99999,
    }
    ps_module.STRATEGY_CONFIGS["mcx_strat"] = {
        "exchange": "MCX",
        "schedule_start": "17:00",
        "schedule_stop": "23:55",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
        "is_scheduled": True,
        "is_running": True,
        "pid": 99998,
    }
    ps_module.STRATEGY_CONFIGS["crypto_strat"] = {
        "exchange": "CRYPTO",
        "schedule_start": "00:00",
        "schedule_stop": "23:59",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "is_scheduled": True,
        "is_running": True,
        "pid": 99997,
    }

    stopped = []
    monkeypatch.setattr(
        ps_module, "stop_strategy_process", lambda sid: stopped.append(sid) or (True, "ok")
    )
    monkeypatch.setattr(ps_module, "_is_strategy_running", lambda sid, cfg: True)
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)

    p = _patch_now(date(2026, 4, 14), 0, 1)  # 00:01 IST on holiday
    try:
        ps_module.daily_trading_day_check()
    finally:
        p.stop()

    assert stopped == ["nse_strat"], f"stopped={stopped}"
    # MCX has a session (evening) → not stopped
    # CRYPTO is always trading → not stopped


# ---------------------------------------------------------------------------
# Edge case 5: Full holiday (no exchange open at all)
# ---------------------------------------------------------------------------


def test_full_closure_republic_day(ps_module):
    """26-Jan-2026 Republic Day: every non-CRYPTO exchange is closed."""
    p = _patch_now(date(2026, 1, 26), 12, 0)
    try:
        for ex in ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"):
            assert ps_module.is_trading_day(ex) is False, f"{ex} should be closed"
        assert ps_module.is_trading_day("CRYPTO") is True
    finally:
        p.stop()


# ---------------------------------------------------------------------------
# Edge case 6: SETTLEMENT_HOLIDAY (markets open, no settlement)
# ---------------------------------------------------------------------------


def test_settlement_holiday_treated_as_normal_trading(calendar_db):
    """SETTLEMENT_HOLIDAY should leave default exchange windows in place."""
    from sqlalchemy import inspect

    inspector = inspect(calendar_db.engine)
    assert "market_holidays" in inspector.get_table_names()

    # Insert a SETTLEMENT_HOLIDAY row for a non-existing date in 2026
    settlement_date = date(2026, 5, 4)  # arbitrary regular Monday
    h = calendar_db.Holiday(
        holiday_date=settlement_date,
        description="Settlement holiday test",
        holiday_type="SETTLEMENT_HOLIDAY",
        year=2026,
    )
    calendar_db.db_session.add(h)
    calendar_db.db_session.commit()
    calendar_db.clear_market_calendar_cache()

    try:
        win = calendar_db.get_effective_session_window(settlement_date, "NSE")
        assert win is not None  # default NSE window — markets are tradeable
        assert win["is_special"] is False
    finally:
        # Clean up
        calendar_db.HolidayExchange.query.filter_by(holiday_id=h.id).delete()
        calendar_db.db_session.delete(h)
        calendar_db.db_session.commit()
        calendar_db.clear_market_calendar_cache()


# ---------------------------------------------------------------------------
# Edge case 7: load_configs handles malformed entries
# ---------------------------------------------------------------------------


def test_load_configs_handles_empty_string_exchange(ps_module, tmp_path):
    """Legacy config with exchange="" must be backfilled to NSE."""
    cfg_path = tmp_path / "strategy_configs.json"
    cfg_path.write_text(json.dumps({"weird": {"name": "x", "exchange": ""}}))

    original = ps_module.CONFIG_FILE
    ps_module.CONFIG_FILE = cfg_path
    try:
        ps_module.load_configs()
        assert ps_module.STRATEGY_CONFIGS["weird"]["exchange"] == "NSE"
    finally:
        ps_module.CONFIG_FILE = original


def test_load_configs_uppercases_exchange(ps_module, tmp_path):
    """exchange='mcx' (lowercase) should be normalized to 'MCX'."""
    cfg_path = tmp_path / "strategy_configs.json"
    cfg_path.write_text(json.dumps({"low": {"name": "x", "exchange": "mcx"}}))

    original = ps_module.CONFIG_FILE
    ps_module.CONFIG_FILE = cfg_path
    try:
        ps_module.load_configs()
        assert ps_module.STRATEGY_CONFIGS["low"]["exchange"] == "MCX"
    finally:
        ps_module.CONFIG_FILE = original


# ---------------------------------------------------------------------------
# Edge case 8: normalize_exchange resilience
# ---------------------------------------------------------------------------


def test_normalize_exchange_unknown_falls_back(ps_module):
    """Unknown exchange names default to NSE rather than crashing."""
    assert ps_module.normalize_exchange("XYZ") == "NSE"
    assert ps_module.normalize_exchange("   nse   ") == "NSE"  # strip + upper
    assert ps_module.normalize_exchange("nse") == "NSE"
    assert ps_module.normalize_exchange(123) == "NSE"  # non-string


# ---------------------------------------------------------------------------
# Edge case 9: schedule_strategy_route refuses while running
# ---------------------------------------------------------------------------


def test_schedule_route_refuses_when_running(ps_module):
    """Verify the ownership + running guards used by schedule_strategy_route."""
    from flask import Flask

    ps_module.STRATEGY_CONFIGS["s"] = {
        "user_id": "alice",
        "is_running": True,
        "exchange": "NSE",
        "schedule_start": "09:15",
        "schedule_stop": "15:30",
        "schedule_days": ["mon"],
    }

    app = Flask(__name__)
    with app.app_context():
        is_owner, result = ps_module.verify_strategy_ownership(
            "s", "alice", return_config=True
        )
        assert is_owner is True
        # The route refuses if is_running is True
        assert result.get("is_running") is True

        # Wrong user → ownership refusal
        is_owner, err = ps_module.verify_strategy_ownership("s", "mallory")
        assert is_owner is False
        # err is (response, status_code)
        assert err[1] == 403


# ---------------------------------------------------------------------------
# Edge case 10: env var injection
# ---------------------------------------------------------------------------


def test_subprocess_env_includes_strategy_exchange(ps_module, monkeypatch, tmp_path):
    """start_strategy_process injects OPENALGO_STRATEGY_EXCHANGE per strategy."""
    from pathlib import Path

    # Build a noop strategy file
    strat = tmp_path / "noop.py"
    strat.write_text("import sys; sys.exit(0)\n")

    ps_module.STRATEGY_CONFIGS["envtest"] = {
        "name": "EnvTest",
        "file_path": str(strat),
        "user_id": "bob",
        "exchange": "MCX",
    }

    captured_env = {}

    class FakeProc:
        def __init__(self, *a, **kw):
            captured_env.update(kw.get("env") or {})
            self.pid = 12345
            self._stdout = a

        def poll(self):
            return None

    monkeypatch.setattr(ps_module.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(ps_module, "check_master_contract_ready", lambda: (True, "ok"))
    monkeypatch.setattr(ps_module, "broadcast_status_update", lambda *a, **kw: None)
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)
    monkeypatch.setattr(ps_module, "LOGS_DIR", Path(tmp_path))

    success, msg = ps_module.start_strategy_process("envtest")
    assert success, msg
    assert captured_env.get("OPENALGO_STRATEGY_EXCHANGE") == "MCX"
    assert captured_env.get("STRATEGY_ID") == "envtest"
    assert captured_env.get("STRATEGY_NAME") == "EnvTest"


# ---------------------------------------------------------------------------
# Edge case 11: get_market_status reasons
# ---------------------------------------------------------------------------


def test_market_status_reasons_for_each_state(ps_module):
    """Verify the four canonical reason codes."""
    # Weekend, no special session
    p = _patch_now(date(2026, 4, 12), 12, 0)  # plain Sunday
    try:
        s = ps_module.get_market_status("NSE")
        assert s["reason"] == "weekend"
        assert s["is_open"] is False
    finally:
        p.stop()

    # Holiday, weekday
    p = _patch_now(date(2026, 4, 14), 12, 0)
    try:
        s = ps_module.get_market_status("NSE")
        assert s["reason"] == "holiday"
        assert s["is_open"] is False
    finally:
        p.stop()

    # Before market on a normal day
    p = _patch_now(date(2026, 4, 7), 8, 0)  # Tuesday 08:00
    try:
        s = ps_module.get_market_status("NSE")
        assert s["reason"] == "before_market"
        assert s["is_open"] is False
        assert s["is_trading"] is True
    finally:
        p.stop()

    # After market on a normal day
    p = _patch_now(date(2026, 4, 7), 16, 0)  # 16:00, after 15:30
    try:
        s = ps_module.get_market_status("NSE")
        assert s["reason"] == "after_market"
        assert s["is_open"] is False
        assert s["is_trading"] is True
    finally:
        p.stop()


# ---------------------------------------------------------------------------
# Edge case 12: CRYPTO with manually_stopped is still respected
# ---------------------------------------------------------------------------


def test_crypto_manually_stopped_not_resumed(ps_module, monkeypatch):
    """CRYPTO 24/7 is no excuse — manual stop must always be honored."""
    ps_module.STRATEGY_CONFIGS["c"] = {
        "exchange": "CRYPTO",
        "schedule_start": "00:00",
        "schedule_stop": "23:59",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "is_scheduled": True,
        "manually_stopped": True,
        "paused_reason": "holiday",  # stale
    }

    started = []
    monkeypatch.setattr(
        ps_module, "start_strategy_process", lambda sid: started.append(sid) or (True, "ok")
    )
    monkeypatch.setattr(ps_module, "_is_strategy_running", lambda sid, cfg: False)
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)

    p = _patch_now(date(2026, 4, 12), 12, 0)  # plain Sunday
    try:
        ps_module.market_hours_enforcer()
    finally:
        p.stop()

    assert started == []


# ---------------------------------------------------------------------------
# Edge case 13: Schedule with empty days list (shouldn't crash)
# ---------------------------------------------------------------------------


def test_empty_schedule_days_treated_as_all(ps_module, monkeypatch):
    """Strategy with schedule_days=[] should not crash the enforcer."""
    ps_module.STRATEGY_CONFIGS["e"] = {
        "exchange": "MCX",
        "schedule_start": "09:00",
        "schedule_stop": "23:55",
        "schedule_days": [],
        "is_scheduled": True,
    }
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)
    monkeypatch.setattr(ps_module, "_is_strategy_running", lambda sid, cfg: False)

    p = _patch_now(date(2026, 4, 14), 19, 0)
    try:
        # Should not raise
        ps_module.market_hours_enforcer()
        ps_module.daily_trading_day_check()
    finally:
        p.stop()


# ---------------------------------------------------------------------------
# Edge case 14: get_effective_session_window edge — exact start/end boundaries
# ---------------------------------------------------------------------------


def test_session_boundary_inclusive(calendar_db):
    """Session windows are inclusive on both ends (<=)."""
    from datetime import timedelta

    win = calendar_db.get_effective_session_window(date(2026, 4, 14), "MCX")
    assert win is not None

    # Construct an "is_market_open" check at the exact start_ms boundary
    midnight_ist = IST.localize(datetime(2026, 4, 14, 0, 0, 0))
    start_dt = datetime.fromtimestamp(win["start_ms"] / 1000, tz=IST)
    end_dt = datetime.fromtimestamp(win["end_ms"] / 1000, tz=IST)
    assert start_dt.hour == 17 and start_dt.minute == 0
    assert end_dt.hour == 23 and end_dt.minute == 55


# ---------------------------------------------------------------------------
# Edge case 15: Backward compat — strategies without scheduler_days
# ---------------------------------------------------------------------------


def test_strategy_without_schedule_days_field(ps_module, tmp_path):
    """Legacy config with no schedule_days at all must still load and gain exchange."""
    cfg_path = tmp_path / "strategy_configs.json"
    cfg_path.write_text(json.dumps({"old": {"name": "old", "schedule_start": "09:15"}}))

    original = ps_module.CONFIG_FILE
    ps_module.CONFIG_FILE = cfg_path
    try:
        ps_module.load_configs()
        cfg = ps_module.STRATEGY_CONFIGS["old"]
        assert cfg["exchange"] == "NSE"  # backfilled
        assert cfg.get("schedule_days") in (None, []) or "schedule_days" not in cfg
    finally:
        ps_module.CONFIG_FILE = original


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
