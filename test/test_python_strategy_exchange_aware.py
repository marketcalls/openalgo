"""Tests for the exchange-aware /python strategy hosting calendar.

Covers the matrix:
  - 14-Apr-2026: NSE/BSE/NFO/BFO/CDS/BCD closed, MCX evening 17:00-23:55
  - 8-Nov-2026 (Sunday): SPECIAL_SESSION (Diwali Muhurat) 18:00-19:15 NSE/BSE
  - Plain Sunday: only CRYPTO trades
  - CRYPTO is unaffected by all of the above

Run inside the project root:
    uv run pytest test/test_python_strategy_exchange_aware.py -v
"""

import os
import sys
from datetime import date, datetime
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force in-memory DB before importing market_calendar_db
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytz  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Shared session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def calendar_db():
    """Create a single in-memory market calendar DB, seeded with 2026 holidays."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.pool import StaticPool

    import database.market_calendar_db as mc

    # StaticPool keeps a single SQLite :memory: connection alive across the
    # whole session — without it each pool-checkout sees a fresh, empty in-memory DB.
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
    """Reset state on the (single) python_strategy module instance.

    We deliberately don't re-import: `from blueprints import python_strategy`
    after sys.modules.pop returns the *old* cached module on the parent
    package, while `patch('blueprints.python_strategy.datetime')` triggers
    a fresh import — patching a different instance than the test sees. The
    cleanest fix is to import once and reset the per-test mutable state.
    """
    from blueprints import python_strategy as ps

    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()
    # Always work against an empty cache so test ordering doesn't poison results
    calendar_db.clear_market_calendar_cache()
    yield ps
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()


def _patch_now(ps_mod, target_date: date, hour: int, minute: int = 0):
    """Patch python_strategy.datetime.now() to return a fixed IST timestamp."""
    fixed_now = IST.localize(
        datetime(target_date.year, target_date.month, target_date.day, hour, minute, 0)
    )
    patcher = patch("blueprints.python_strategy.datetime")
    mock_dt = patcher.start()
    mock_dt.now.return_value = fixed_now
    mock_dt.combine = datetime.combine
    mock_dt.fromisoformat = datetime.fromisoformat
    mock_dt.fromtimestamp = datetime.fromtimestamp
    mock_dt.min = datetime.min  # for datetime.combine(date, datetime.min.time())
    mock_dt.max = datetime.max
    return patcher


# ---------------------------------------------------------------------------
# market_calendar_db helpers
# ---------------------------------------------------------------------------


def test_special_session_on_sunday(calendar_db):
    """Diwali Muhurat 8-Nov-2026 (Sunday) returns special-session window for NSE."""
    sunday = date(2026, 11, 8)
    assert sunday.weekday() == 6  # Sunday

    special = calendar_db.get_special_session(sunday, "NSE")
    assert special is not None, "Sunday Muhurat must be discoverable"
    assert special["start_ms"] < special["end_ms"]
    assert "Muhurat" in special["description"] or "Diwali" in special["description"]


def test_special_session_returns_none_for_non_special_holiday(calendar_db):
    """A regular TRADING_HOLIDAY must NOT be reported as a special session."""
    assert calendar_db.get_special_session(date(2026, 4, 14), "NSE") is None


def test_holiday_exchange_window_mcx_on_nse_holiday(calendar_db):
    """14-Apr-2026: MCX has explicit evening window even though NSE is closed."""
    win = calendar_db.get_holiday_exchange_window(date(2026, 4, 14), "MCX")
    assert win is not None
    assert win["start_ms"] < win["end_ms"]


def test_effective_session_window_matrix(calendar_db):
    """get_effective_session_window resolves the four key cases."""
    # 14-Apr-2026: NSE closed, MCX has evening window
    assert calendar_db.get_effective_session_window(date(2026, 4, 14), "NSE") is None
    mcx_win = calendar_db.get_effective_session_window(date(2026, 4, 14), "MCX")
    assert mcx_win is not None
    assert mcx_win["is_special"] is True

    # 8-Nov-2026 Sunday Muhurat: NSE has special window
    nse_muhurat = calendar_db.get_effective_session_window(date(2026, 11, 8), "NSE")
    assert nse_muhurat is not None
    assert nse_muhurat["is_special"] is True

    # Plain Sunday 12-Apr-2026: NSE closed
    assert date(2026, 4, 12).weekday() == 6
    assert calendar_db.get_effective_session_window(date(2026, 4, 12), "NSE") is None

    # CRYPTO always has a window
    crypto_win = calendar_db.get_effective_session_window(date(2026, 4, 12), "CRYPTO")
    assert crypto_win is not None
    assert crypto_win["is_special"] is False


def test_is_market_holiday_per_exchange(calendar_db):
    """is_market_holiday respects the per-exchange override on partial holidays."""
    apr14 = date(2026, 4, 14)
    assert calendar_db.is_market_holiday(apr14, "NSE") is True
    assert calendar_db.is_market_holiday(apr14, "MCX") is False  # MCX explicitly open


def test_is_market_holiday_special_session_overrides_weekend(calendar_db):
    """SPECIAL_SESSION on Sunday must NOT be reported as a holiday."""
    sunday_muhurat = date(2026, 11, 8)
    assert calendar_db.is_market_holiday(sunday_muhurat) is False
    assert calendar_db.is_market_holiday(sunday_muhurat, "NSE") is False


def test_crypto_never_a_holiday(calendar_db):
    """CRYPTO never has holidays, even on full closure days."""
    assert calendar_db.is_market_holiday(date(2026, 1, 26), "CRYPTO") is False
    assert calendar_db.is_market_holiday(date(2026, 4, 12), "CRYPTO") is False


# ---------------------------------------------------------------------------
# python_strategy.py exchange-aware helpers
# ---------------------------------------------------------------------------


def test_is_trading_day_per_exchange_on_apr14(ps_module):
    """14-Apr-2026: MCX strategy is_trading_day=True, NSE strategy=False, CRYPTO=True."""
    patcher = _patch_now(ps_module, date(2026, 4, 14), 18, 30)
    try:
        assert ps_module.is_trading_day("NSE") is False
        assert ps_module.is_trading_day("BSE") is False
        assert ps_module.is_trading_day("MCX") is True
        assert ps_module.is_trading_day("CRYPTO") is True
    finally:
        patcher.stop()


def test_is_trading_day_sunday_muhurat(ps_module):
    """Sunday Muhurat (8-Nov-2026): NSE strategy is_trading_day=True."""
    patcher = _patch_now(ps_module, date(2026, 11, 8), 18, 30)
    try:
        assert ps_module.is_trading_day("NSE") is True
        # MCX Muhurat is also seeded
        assert ps_module.is_trading_day("MCX") is True
    finally:
        patcher.stop()


def test_is_trading_day_plain_sunday(ps_module):
    """Plain Sunday (no special session): all non-CRYPTO exchanges return False."""
    patcher = _patch_now(ps_module, date(2026, 4, 12), 12, 0)
    try:
        assert ps_module.is_trading_day("NSE") is False
        assert ps_module.is_trading_day("MCX") is False
        assert ps_module.is_trading_day("CRYPTO") is True
    finally:
        patcher.stop()


def test_get_market_status_mcx_evening_session_inside_window(ps_module):
    """14-Apr-2026 19:00 IST: MCX status.is_open=True, is_special=True; NSE closed."""
    patcher = _patch_now(ps_module, date(2026, 4, 14), 19, 0)
    try:
        nse_status = ps_module.get_market_status("NSE")
        assert nse_status["is_open"] is False
        assert nse_status["is_trading"] is False

        mcx_status = ps_module.get_market_status("MCX")
        assert mcx_status["is_open"] is True
        assert mcx_status["is_trading"] is True
        assert mcx_status["is_special"] is True

        crypto_status = ps_module.get_market_status("CRYPTO")
        assert crypto_status["is_open"] is True
    finally:
        patcher.stop()


def test_get_market_status_mcx_before_session_window(ps_module):
    """14-Apr-2026 10:00 IST: MCX evening hasn't opened yet (17:00)."""
    patcher = _patch_now(ps_module, date(2026, 4, 14), 10, 0)
    try:
        mcx_status = ps_module.get_market_status("MCX")
        assert mcx_status["is_open"] is False
        assert mcx_status["is_trading"] is True
        assert mcx_status["reason"] == "before_market"
    finally:
        patcher.stop()


def test_normalize_exchange_defaults_and_validation(ps_module):
    """normalize_exchange falls back to NSE for None/unknown."""
    assert ps_module.normalize_exchange(None) == "NSE"
    assert ps_module.normalize_exchange("") == "NSE"
    assert ps_module.normalize_exchange("foobar") == "NSE"
    assert ps_module.normalize_exchange("mcx") == "MCX"
    assert ps_module.normalize_exchange("crypto") == "CRYPTO"


def test_within_schedule_intersects_special_session(ps_module):
    """User schedule 09:15-15:30 on 14-Apr-2026 MCX: must NOT be within window
    even at 19:00 because 19:00 > 15:30 (user's own stop)."""
    ps_module.STRATEGY_CONFIGS["t1"] = {
        "exchange": "MCX",
        "schedule_start": "09:15",
        "schedule_stop": "15:30",
    }

    patcher = _patch_now(ps_module, date(2026, 4, 14), 19, 0)
    try:
        # 19:00 outside user's 09:15-15:30, MCX session 17:00-23:55. Intersection empty -> False
        assert ps_module.is_within_schedule_time("t1") is False
    finally:
        patcher.stop()

    # Widen user's schedule to cover the MCX evening session
    ps_module.STRATEGY_CONFIGS["t1"]["schedule_start"] = "17:00"
    ps_module.STRATEGY_CONFIGS["t1"]["schedule_stop"] = "23:55"

    patcher = _patch_now(ps_module, date(2026, 4, 14), 19, 0)
    try:
        assert ps_module.is_within_schedule_time("t1") is True
    finally:
        patcher.stop()


def test_crypto_within_schedule_24x7(ps_module):
    """CRYPTO with 00:00-23:59 schedule is always within window, including weekends."""
    ps_module.STRATEGY_CONFIGS["c1"] = {
        "exchange": "CRYPTO",
        "schedule_start": "00:00",
        "schedule_stop": "23:59",
    }

    for hh in (0, 6, 12, 18, 23):
        patcher = _patch_now(ps_module, date(2026, 4, 12), hh, 30)  # plain Sunday
        try:
            assert ps_module.is_within_schedule_time("c1") is True, f"failed at {hh}:30"
        finally:
            patcher.stop()


def test_load_configs_backfills_exchange(ps_module, tmp_path):
    """Legacy strategy_configs.json without exchange must be backfilled to NSE."""
    import json

    legacy = {"legacy_strat": {"name": "old", "schedule_start": "09:15"}}
    cfg_path = tmp_path / "strategy_configs.json"
    cfg_path.write_text(json.dumps(legacy))

    original = ps_module.CONFIG_FILE
    ps_module.CONFIG_FILE = cfg_path
    try:
        ps_module.load_configs()
        assert ps_module.STRATEGY_CONFIGS["legacy_strat"]["exchange"] == "NSE"
    finally:
        ps_module.CONFIG_FILE = original


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
