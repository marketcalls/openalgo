"""Phase 3 — RMS engine integration tests.

Validates the wiring between the engine, the market_data_service tick
callback, and the exit_service trigger path. Uses an in-memory SQLite engine
+ a fake market_data_service so no real DB or broker calls happen.

Each test seeds a strategy + leg + position + run row, registers the run
with the engine, then drives synthetic ticks through the on-tick callback
and asserts the engine called close_leg with the right arguments.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Test infrastructure — in-memory DB + fresh engine + fake market_data_service
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

    from services.strategy import position_tracker, rms_engine, exit_service

    monkeypatch.setattr(position_tracker, "db_session", Session)
    monkeypatch.setattr(rms_engine, "db_session", Session)
    monkeypatch.setattr(exit_service, "db_session", Session)

    strategy_v2_db.Base.metadata.create_all(bind=engine)
    yield Session
    Session.remove()
    engine.dispose()


@pytest.fixture
def clean_engine():
    """Reset the singleton engine state between tests."""
    from services.strategy.rms_engine import engine as rms

    rms._runs.clear()
    rms._symbol_to_runs.clear()
    rms._subscriber_id = None
    yield rms
    rms._runs.clear()
    rms._symbol_to_runs.clear()
    rms._subscriber_id = None


@pytest.fixture
def fake_mds(monkeypatch):
    """Replace market_data_service with a stub. Tests drive ticks by calling
    engine._on_tick directly — they don't need real subscribe behavior."""
    fake = MagicMock()
    fake.subscribe_critical = MagicMock(return_value=42)
    fake.unsubscribe_priority = MagicMock(return_value=True)
    fake.is_trade_management_safe = MagicMock(return_value=(True, ""))

    import services.market_data_service as mds_mod
    monkeypatch.setattr(mds_mod, "get_market_data_service", lambda: fake)
    yield fake


@pytest.fixture
def fake_close_leg(monkeypatch):
    """Capture close_leg calls so tests can assert on them without placing
    real orders."""
    calls = []

    def _fake_close_leg(*, run_id, leg_id, reason, rms_event_id=None):
        calls.append({"run_id": run_id, "leg_id": leg_id, "reason": reason})
        return True, {"status": "success", "leg_id": leg_id}

    from services.strategy import exit_service
    monkeypatch.setattr(exit_service, "close_leg", _fake_close_leg)
    # Also patch the import inside rms_engine since that's a `from import` reference
    import services.strategy.rms_engine as eng_mod
    yield calls


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_full_run(session, *, leg_overrides=None, position_overrides=None):
    """Seed a complete strategy + leg + position + IN_TRADE run.

    Returns (strategy_id, leg_id, run_id, position_id).
    """
    from database.strategy_v2_db import (
        StrategyLeg, StrategyPosition, StrategyRun, StrategyV2,
    )

    s = StrategyV2(
        name="Test", webhook_id="test-uuid", user_id="tester",
        underlying="NIFTY", underlying_exchange="NSE_INDEX",
        is_intraday=True, start_time="09:15", end_time="15:30",
        state="ARMED", is_active=True, mode="live",
        webhook_signing_method="NONE",
    )
    session.add(s)
    session.flush()

    leg_def = dict(
        strategy_id=s.id, leg_index=1, segment="CASH",
        position="B", product="MIS",
        symbol_cash="INFY", qty=50,
        sl_enabled=True, sl_value=Decimal("10"), sl_unit="pts",
        target_enabled=True, target_value=Decimal("20"), target_unit="pts",
        trail_enabled=False,
        resolved_symbol="INFY", resolved_exchange="NSE",
        lot_size_cache=1, tick_size_cache=Decimal("0.05"),
    )
    if leg_overrides:
        leg_def.update(leg_overrides)
    leg = StrategyLeg(**leg_def)
    session.add(leg)
    session.flush()

    run = StrategyRun(strategy_id=s.id, state="IN_TRADE", mode="live")
    session.add(run)
    session.flush()

    pos_def = dict(
        strategy_id=s.id, run_id=run.id, leg_id=leg.id,
        symbol="INFY", exchange="NSE", product="MIS",
        net_qty=50, avg_entry=Decimal("1500"),
        quantity="50", average_price="1500", ltp="1500", pnl="0",
        leg_state="OPEN",
        last_trail_anchor=Decimal("1500"),
    )
    if position_overrides:
        pos_def.update(position_overrides)
    pos = StrategyPosition(**pos_def)
    session.add(pos)
    session.commit()
    return s.id, leg.id, run.id, pos.id


def _tick(symbol="INFY", exchange="NSE", ltp=1500.0, mode=1):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "mode": mode,
        "data": {"ltp": ltp},
    }


# ---------------------------------------------------------------------------
# Registration / lifecycle
# ---------------------------------------------------------------------------


def test_register_run_pulls_legs_into_memory(in_memory_db, clean_engine, fake_mds):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    ok = clean_engine.register_run(rid)
    assert ok is True
    assert rid in clean_engine.active_run_ids()
    assert "NSE:INFY" in clean_engine._symbol_to_runs


def test_register_run_idempotent(in_memory_db, clean_engine, fake_mds):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    assert clean_engine.register_run(rid) is True
    assert clean_engine.register_run(rid) is True  # second call no-op
    assert len(clean_engine.active_run_ids()) == 1


def test_unregister_run_clears_state(in_memory_db, clean_engine, fake_mds):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)
    clean_engine.unregister_run(rid)
    assert clean_engine.active_run_ids() == []
    assert "NSE:INFY" not in clean_engine._symbol_to_runs


def test_register_skips_non_in_trade_run(in_memory_db, clean_engine, fake_mds):
    from database.strategy_v2_db import StrategyRun

    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    in_memory_db.query(StrategyRun).filter(StrategyRun.id == rid).update({"state": "ENTERING"})
    in_memory_db.commit()
    assert clean_engine.register_run(rid) is False


def test_state_changed_to_in_trade_registers(in_memory_db, clean_engine, fake_mds):
    from types import SimpleNamespace

    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    event = SimpleNamespace(
        new_state="IN_TRADE", old_state="ENTERING",
        run_id=rid, strategy_id=sid, reason="all entries filled",
    )
    clean_engine.on_state_changed(event)
    assert rid in clean_engine.active_run_ids()


def test_state_changed_to_terminal_unregisters(in_memory_db, clean_engine, fake_mds):
    from types import SimpleNamespace

    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)

    for terminal in ("EXITING", "CLOSED", "EXIT_FAILED", "ERRORED", "STOPPED"):
        clean_engine.register_run(rid)  # re-register
        ev = SimpleNamespace(
            new_state=terminal, old_state="IN_TRADE",
            run_id=rid, strategy_id=sid,
        )
        clean_engine.on_state_changed(ev)
        assert rid not in clean_engine.active_run_ids()


# ---------------------------------------------------------------------------
# Tick → SL trigger
# ---------------------------------------------------------------------------


def test_long_sl_hit_triggers_exit(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)

    # SL configured at 1490 (entry 1500 - 10pts). Tick to 1489 → trigger.
    clean_engine._on_tick(_tick(ltp=1489.0))

    assert fake_close_leg, "exit was not fired"
    assert fake_close_leg[0]["run_id"] == rid
    assert fake_close_leg[0]["leg_id"] == lid
    assert fake_close_leg[0]["reason"] == "exit_leg_sl"


def test_long_sl_not_hit_no_exit(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)
    clean_engine._on_tick(_tick(ltp=1495.0))  # above SL of 1490
    assert fake_close_leg == []


def test_short_sl_hit_triggers_exit(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(
        in_memory_db,
        leg_overrides={"position": "S"},
        position_overrides={"net_qty": -50},
    )
    clean_engine.register_run(rid)

    # Short SL = entry + 10 = 1510. Tick above triggers.
    clean_engine._on_tick(_tick(ltp=1511.0))
    assert fake_close_leg
    assert fake_close_leg[0]["reason"] == "exit_leg_sl"


# ---------------------------------------------------------------------------
# Tick → target trigger
# ---------------------------------------------------------------------------


def test_long_target_hit_triggers_exit(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)
    # Target = entry + 20 = 1520
    clean_engine._on_tick(_tick(ltp=1521.0))
    assert fake_close_leg
    assert fake_close_leg[0]["reason"] == "exit_leg_target"


# ---------------------------------------------------------------------------
# Trail X/Y
# ---------------------------------------------------------------------------


def test_trail_advances_persist(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    """Favorable move advances trail and persists current_sl_price."""
    from database.strategy_v2_db import StrategyPosition

    sid, lid, rid, pid = _seed_full_run(
        in_memory_db,
        leg_overrides={
            "trail_enabled": True,
            "trail_x": Decimal("1"), "trail_y": Decimal("2"), "trail_unit": "pts",
        },
        position_overrides={
            "current_sl_price": Decimal("1490"),
            "last_trail_anchor": Decimal("1500"),
        },
    )
    clean_engine.register_run(rid)

    # 5pt favorable → 5 advances × 2pt = SL moves to 1500
    clean_engine._on_tick(_tick(ltp=1505.0))

    # Engine kept the leg active (not yet hitting SL)
    assert fake_close_leg == []
    # Position row reflects new SL
    pos = in_memory_db.query(StrategyPosition).filter(StrategyPosition.id == pid).first()
    assert float(pos.current_sl_price) == 1500.0
    assert pos.trail_advances_count == 5


def test_trail_one_way_no_relax_on_retracement(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    """Price moves up then back — SL must not move down."""
    from database.strategy_v2_db import StrategyPosition

    sid, lid, rid, pid = _seed_full_run(
        in_memory_db,
        leg_overrides={
            "trail_enabled": True,
            "trail_x": Decimal("1"), "trail_y": Decimal("2"), "trail_unit": "pts",
        },
        position_overrides={
            "current_sl_price": Decimal("1490"),
            "last_trail_anchor": Decimal("1500"),
        },
    )
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick(ltp=1505.0))  # advance 5x → SL=1500
    clean_engine._on_tick(_tick(ltp=1502.0))  # retrace
    pos = in_memory_db.query(StrategyPosition).filter(StrategyPosition.id == pid).first()
    assert float(pos.current_sl_price) == 1500.0  # held


def test_trail_then_sl_hit_after_retrace(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    """After trail advances SL to 1500, a tick at 1499 should trigger SL."""
    sid, lid, rid, pid = _seed_full_run(
        in_memory_db,
        leg_overrides={
            "trail_enabled": True,
            "trail_x": Decimal("1"), "trail_y": Decimal("2"), "trail_unit": "pts",
            # Disable hard target so only trail+SL fire
            "target_enabled": False,
        },
        position_overrides={
            "current_sl_price": Decimal("1490"),
            "last_trail_anchor": Decimal("1500"),
        },
    )
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick(ltp=1505.0))  # trail to 1500
    assert fake_close_leg == []
    clean_engine._on_tick(_tick(ltp=1499.0))  # SL crossed
    assert fake_close_leg
    assert fake_close_leg[0]["reason"] == "exit_leg_sl"


# ---------------------------------------------------------------------------
# Safety gates
# ---------------------------------------------------------------------------


def test_stale_feed_skips_evaluation(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)
    fake_mds.is_trade_management_safe.return_value = (False, "stale")
    clean_engine._on_tick(_tick(ltp=1000.0))  # would normally trigger
    assert fake_close_leg == []


def test_invalid_ltp_skipped(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)
    clean_engine._on_tick(_tick(ltp=0))  # 0 LTP rejected
    clean_engine._on_tick(_tick(ltp=-1))  # negative rejected
    clean_engine._on_tick({"symbol": "INFY", "exchange": "NSE", "data": {}})  # missing
    assert fake_close_leg == []


def test_unregistered_symbol_ignored(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)
    clean_engine._on_tick(_tick(symbol="WIPRO", ltp=1000.0))
    assert fake_close_leg == []


# ---------------------------------------------------------------------------
# Idempotency — once exit fired, leg drops out
# ---------------------------------------------------------------------------


def test_exit_fires_once_then_leg_drops(in_memory_db, clean_engine, fake_mds, fake_close_leg):
    sid, lid, rid, pid = _seed_full_run(in_memory_db)
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick(ltp=1489.0))  # SL hit
    clean_engine._on_tick(_tick(ltp=1488.0))  # would also hit, but leg unregistered
    assert len(fake_close_leg) == 1
