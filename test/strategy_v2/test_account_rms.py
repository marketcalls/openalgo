"""Phase 4.5 — account-level RMS tests.

Covers preflight gates, lifecycle counters (active_run_count, realized_pnl
today by mode), lock-on-loss-cap, manual unlock, auto-clear computation.

Uses an in-memory SQLite engine (StaticPool) so tests don't touch
db/openalgo.db.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

    from database import strategy_v2_db
    monkeypatch.setattr(strategy_v2_db, "engine", engine)
    monkeypatch.setattr(strategy_v2_db, "db_session", Session)

    from services.strategy import account_rms
    monkeypatch.setattr(account_rms, "db_session", Session)

    strategy_v2_db.Base.metadata.create_all(bind=engine)
    yield Session
    Session.remove()
    engine.dispose()


@pytest.fixture
def captured_events():
    """Snoop on account.* topics."""
    from utils.event_bus import bus

    captured = []

    def _capture(ev):
        captured.append(ev)

    for t in ("account.locked", "account.unlocked"):
        bus.subscribe(t, _capture, f"test:{t}")

    yield captured

    for t in ("account.locked", "account.unlocked"):
        bus.unsubscribe(t, _capture)


def _seed_strategy(session, user_id="alice"):
    """Seed a strategy and return a SimpleNamespace with primitive fields.

    Returning the ORM object directly is fragile — account_rms.on_state_changed
    calls db_session.remove() at the end of every call, which detaches the
    ORM object so subsequent attribute access (e.g. test reading s.user_id)
    triggers a DetachedInstanceError. Tests want primitives, not the live
    SQLAlchemy row.
    """
    from database.strategy_v2_db import StrategyV2

    s = StrategyV2(
        name="S", webhook_id=f"uuid-{user_id}-{session.bind.url}",
        user_id=user_id, is_intraday=True,
        start_time="09:15", end_time="15:30",
        state="ARMED", is_active=True, mode="live",
        webhook_signing_method="NONE",
    )
    session.add(s)
    session.commit()
    return SimpleNamespace(id=s.id, user_id=s.user_id, name=s.name)


# ===========================================================================
# Preflight — happy path
# ===========================================================================


def test_preflight_passes_with_default_config(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    allowed, reason = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is True
    assert reason == ""


def test_get_or_create_config_lazy_creates(in_memory_db):
    from database.strategy_v2_db import AccountRiskConfig
    from services.strategy import account_rms

    cfg = account_rms.get_or_create_config("new_user")
    assert cfg.user_id == "new_user"
    assert in_memory_db.query(AccountRiskConfig).count() == 1
    # Idempotent
    cfg2 = account_rms.get_or_create_config("new_user")
    assert cfg2.user_id == "new_user"
    assert in_memory_db.query(AccountRiskConfig).count() == 1


# ===========================================================================
# Preflight — lockout
# ===========================================================================


def test_preflight_blocks_when_locked(in_memory_db, captured_events):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    account_rms.lock_account(
        s.user_id, reason="DAILY_LOSS_CAP", cumulative_loss=-9999,
    )
    allowed, reason = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is False
    assert "locked" in reason.lower()


def test_lockout_auto_clears_when_until_passes(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    account_rms.lock_account(s.user_id, reason="TEST", until=past)
    cfg = account_rms.get_or_create_config(s.user_id)
    # is_locked_now auto-clears expired locks
    assert account_rms.is_locked_now(cfg) is False
    cfg2 = account_rms.get_or_create_config(s.user_id)
    assert cfg2.is_locked_out is False


def test_lockout_holds_until_until_passes(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    account_rms.lock_account(s.user_id, reason="TEST", until=future)
    cfg = account_rms.get_or_create_config(s.user_id)
    assert account_rms.is_locked_now(cfg) is True


def test_unlock_account_clears_state(in_memory_db, captured_events):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    account_rms.lock_account(s.user_id, reason="MANUAL")
    account_rms.unlock_account(s.user_id, cleared_by="test")

    cfg = account_rms.get_or_create_config(s.user_id)
    assert cfg.is_locked_out is False
    assert cfg.lockout_reason is None
    # Both events fired
    topics = [e.topic for e in captured_events]
    assert "account.locked" in topics
    assert "account.unlocked" in topics


# ===========================================================================
# Preflight — concurrent run cap
# ===========================================================================


def test_preflight_blocks_at_concurrent_cap(in_memory_db):
    """Seed actual active runs across two strategies (the active-run
    unique partial index allows only one active run per (strategy_id,
    leg_id_or_zero), so we can't put two on the same strategy without
    leg_ids). The Phase 13.2 self-heal change made the cached counter
    advisory only — concurrent-cap enforcement now reads strategy_runs
    directly."""
    from datetime import datetime, timezone

    from database.strategy_v2_db import StrategyRun, StrategyV2
    from services.strategy import account_rms

    s1 = _seed_strategy(in_memory_db)
    s2 = StrategyV2(
        name="other", webhook_id="other-uuid", user_id=s1.user_id,
        is_intraday=True, start_time="09:15", end_time="15:30",
        state="ARMED", is_active=True, mode="live",
        webhook_signing_method="NONE",
    )
    in_memory_db.add(s2)
    in_memory_db.flush()

    cfg = account_rms.get_or_create_config(s1.user_id)
    cfg.max_concurrent_runs = 2
    in_memory_db.commit()

    for sid in (s1.id, s2.id):
        in_memory_db.add(StrategyRun(
            strategy_id=sid, state="IN_TRADE", mode="live",
            triggered_at=datetime.now(timezone.utc),
            entered_at=datetime.now(timezone.utc),
        ))
    in_memory_db.commit()

    allowed, reason = account_rms.preflight_check(s1.user_id, s1.id)
    assert allowed is False
    assert "max_concurrent_runs" in reason


def test_preflight_passes_below_concurrent_cap(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.max_concurrent_runs = 5
    state = account_rms.get_or_create_state(s.user_id)
    state.active_run_count = 3
    in_memory_db.commit()

    allowed, _ = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is True


# ===========================================================================
# Preflight — daily loss cap
# ===========================================================================


def test_preflight_blocks_at_daily_loss_cap(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.max_daily_loss_abs = Decimal("5000")
    state = account_rms.get_or_create_state(s.user_id)
    state.realized_pnl_today_live = Decimal("-5000")
    in_memory_db.commit()

    allowed, reason = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is False
    assert "daily loss cap" in reason.lower()


def test_preflight_passes_under_daily_loss_cap(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.max_daily_loss_abs = Decimal("5000")
    state = account_rms.get_or_create_state(s.user_id)
    state.realized_pnl_today_live = Decimal("-3000")
    in_memory_db.commit()

    allowed, _ = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is True


def test_preflight_ignores_sandbox_pnl_for_daily_cap(in_memory_db):
    """Sandbox losses are virtual — they don't count against the live
    daily-loss cap."""
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.max_daily_loss_abs = Decimal("5000")
    state = account_rms.get_or_create_state(s.user_id)
    state.realized_pnl_today_sandbox = Decimal("-50000")
    state.realized_pnl_today_live = Decimal("0")
    in_memory_db.commit()

    allowed, _ = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is True


# ===========================================================================
# Lifecycle counters
# ===========================================================================


def test_on_state_changed_in_trade_increments(in_memory_db):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    run = StrategyRun(strategy_id=s.id, state="ENTERING", mode="live")
    in_memory_db.add(run)
    in_memory_db.commit()

    event = SimpleNamespace(
        new_state="IN_TRADE", old_state="ENTERING",
        run_id=run.id, strategy_id=s.id, reason="",
    )
    account_rms.on_state_changed(event)

    state = account_rms.get_or_create_state(s.user_id)
    assert state.active_run_count == 1


def test_on_state_changed_terminal_decrements_and_accumulates(in_memory_db):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    run = StrategyRun(
        strategy_id=s.id, state="EXITING", mode="live",
        realized_pnl=Decimal("1500"),
    )
    in_memory_db.add(run)
    in_memory_db.commit()

    state = account_rms.get_or_create_state(s.user_id)
    state.active_run_count = 3
    in_memory_db.commit()

    event = SimpleNamespace(
        new_state="CLOSED", old_state="EXITING",
        run_id=run.id, strategy_id=s.id, reason="",
    )
    account_rms.on_state_changed(event)

    state2 = account_rms.get_or_create_state(s.user_id)
    assert state2.active_run_count == 2
    assert float(state2.realized_pnl_today_live) == 1500.0


def test_active_run_count_clamps_to_zero(in_memory_db):
    """Defensive: if state somehow drifted (e.g. crash mid-flight), don't
    let the counter go negative."""
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    run = StrategyRun(
        strategy_id=s.id, state="EXITING", mode="live",
        realized_pnl=Decimal("0"),
    )
    in_memory_db.add(run)
    in_memory_db.commit()

    # Counter starts at 0 — shouldn't go to -1.
    event = SimpleNamespace(
        new_state="CLOSED", old_state="EXITING",
        run_id=run.id, strategy_id=s.id, reason="",
    )
    account_rms.on_state_changed(event)
    state = account_rms.get_or_create_state(s.user_id)
    assert state.active_run_count == 0


def test_sandbox_pnl_accumulates_separately(in_memory_db):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    run = StrategyRun(
        strategy_id=s.id, state="EXITING", mode="sandbox",
        realized_pnl=Decimal("500"),
    )
    in_memory_db.add(run)
    in_memory_db.commit()

    event = SimpleNamespace(
        new_state="CLOSED", run_id=run.id, strategy_id=s.id,
    )
    account_rms.on_state_changed(event)

    state = account_rms.get_or_create_state(s.user_id)
    # Live bucket untouched
    assert float(state.realized_pnl_today_live or 0) == 0
    # Sandbox bucket got the gain
    assert float(state.realized_pnl_today_sandbox) == 500.0


# ===========================================================================
# Lock on loss-cap breach
# ===========================================================================


def test_loss_breach_triggers_auto_lock(in_memory_db, captured_events):
    """Configure cap=5000. Run closes with -3000 + another with -2500 → cum
    -5500 which exceeds cap → auto-lock."""
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.max_daily_loss_abs = Decimal("5000")
    in_memory_db.commit()

    # First losing run — under cap, no lock. Seed as CLOSED so the unique
    # partial index on active-states doesn't block run2.
    run1 = StrategyRun(
        strategy_id=s.id, state="CLOSED", mode="live",
        realized_pnl=Decimal("-3000"),
    )
    in_memory_db.add(run1)
    in_memory_db.commit()
    run1_id = run1.id
    account_rms.on_state_changed(
        SimpleNamespace(new_state="CLOSED", run_id=run1_id, strategy_id=s.id)
    )
    cfg2 = account_rms.get_or_create_config(s.user_id)
    assert cfg2.is_locked_out is False

    # Second losing run tips over cap → auto-lock
    run2 = StrategyRun(
        strategy_id=s.id, state="CLOSED", mode="live",
        realized_pnl=Decimal("-2500"),
    )
    in_memory_db.add(run2)
    in_memory_db.commit()
    run2_id = run2.id
    account_rms.on_state_changed(
        SimpleNamespace(new_state="CLOSED", run_id=run2_id, strategy_id=s.id)
    )

    cfg3 = account_rms.get_or_create_config(s.user_id)
    assert cfg3.is_locked_out is True
    assert cfg3.lockout_reason == "DAILY_LOSS_CAP"


def test_no_auto_lock_when_cap_not_configured(in_memory_db, captured_events):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    # No max_daily_loss_abs configured.
    run = StrategyRun(
        strategy_id=s.id, state="EXITING", mode="live",
        realized_pnl=Decimal("-99999"),
    )
    in_memory_db.add(run)
    in_memory_db.commit()
    account_rms.on_state_changed(
        SimpleNamespace(new_state="CLOSED", run_id=run.id, strategy_id=s.id)
    )
    cfg = account_rms.get_or_create_config(s.user_id)
    assert cfg.is_locked_out is False


def test_auto_clear_at_computes_next_ist_occurrence(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.auto_clear_at = "09:00"
    in_memory_db.commit()

    until = account_rms._compute_auto_clear(cfg)
    assert until is not None
    # Sanity: it's in the future
    assert until > datetime.now(timezone.utc)


def test_auto_clear_at_invalid_format_returns_none(in_memory_db):
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.auto_clear_at = "garbage"
    in_memory_db.commit()
    assert account_rms._compute_auto_clear(cfg) is None


# ===========================================================================
# Min seconds between runs (debounce)
# ===========================================================================


def test_debounce_blocks_too_soon(in_memory_db):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.min_seconds_between_runs = 60
    # Recent run triggered 5 seconds ago.
    recent_run = StrategyRun(
        strategy_id=s.id, state="CLOSED", mode="live",
        triggered_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    in_memory_db.add(recent_run)
    in_memory_db.commit()

    allowed, reason = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is False
    assert "debounce" in reason.lower()


def test_debounce_passes_after_window(in_memory_db):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.min_seconds_between_runs = 60
    old_run = StrategyRun(
        strategy_id=s.id, state="CLOSED", mode="live",
        triggered_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )
    in_memory_db.add(old_run)
    in_memory_db.commit()
    allowed, _ = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is True


# ===========================================================================
# Per-strategy daily run cap
# ===========================================================================


def test_per_strategy_daily_cap_blocks(in_memory_db):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.max_runs_per_strategy_per_day = 2

    # Two runs already today.
    for _ in range(2):
        in_memory_db.add(StrategyRun(
            strategy_id=s.id, state="CLOSED", mode="live",
            triggered_at=datetime.now(timezone.utc),
        ))
    in_memory_db.commit()

    allowed, reason = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is False
    assert "run cap" in reason.lower()


def test_per_strategy_daily_cap_only_counts_today(in_memory_db):
    from database.strategy_v2_db import StrategyRun
    from services.strategy import account_rms

    s = _seed_strategy(in_memory_db)
    cfg = account_rms.get_or_create_config(s.user_id)
    cfg.max_runs_per_strategy_per_day = 1

    # Yesterday's run shouldn't count.
    yesterday = datetime.now(timezone.utc) - timedelta(days=1, hours=2)
    in_memory_db.add(StrategyRun(
        strategy_id=s.id, state="CLOSED", mode="live",
        triggered_at=yesterday,
    ))
    in_memory_db.commit()

    allowed, _ = account_rms.preflight_check(s.user_id, s.id)
    assert allowed is True
