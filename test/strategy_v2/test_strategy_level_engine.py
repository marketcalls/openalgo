"""Phase 4 — engine integration tests for strategy-level rules.

Drives synthetic ticks through the engine and asserts:
  - Aggregate MTM computation across multiple legs
  - Overall SL fires exit_strategy with reason="exit_overall_sl"
  - Overall target fires with reason="exit_overall_target"
  - Profit lock arms latch on peak crossing, exits on floor
  - Trail-to-entry pins SL to entry; one-way ratchet
  - peak_mtm + profit_locked persist to strategy_runs

Mocks exit_strategy (don't actually try to place broker orders) and
market_data_service (engine subscribes but tests drive ticks directly).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool


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
    fake = MagicMock()
    fake.subscribe_critical = MagicMock(return_value=42)
    fake.unsubscribe_priority = MagicMock(return_value=True)
    fake.is_trade_management_safe = MagicMock(return_value=(True, ""))
    import services.market_data_service as mds_mod
    monkeypatch.setattr(mds_mod, "get_market_data_service", lambda: fake)
    yield fake


@pytest.fixture
def fake_exit_strategy(monkeypatch):
    """Capture exit_strategy calls so tests can assert without placing orders."""
    calls = []

    def _fake_exit_strategy(*, run_id, reason, rms_event_id=None):
        calls.append({"run_id": run_id, "reason": reason})
        return True, {"status": "success", "legs_exited": 0}

    from services.strategy import exit_service
    monkeypatch.setattr(exit_service, "exit_strategy", _fake_exit_strategy)
    yield calls


@pytest.fixture
def fake_close_leg(monkeypatch):
    calls = []

    def _fake_close_leg(*, run_id, leg_id, reason, rms_event_id=None):
        calls.append({"run_id": run_id, "leg_id": leg_id, "reason": reason})
        return True, {"status": "success"}

    from services.strategy import exit_service
    monkeypatch.setattr(exit_service, "close_leg", _fake_close_leg)
    yield calls


# ---------------------------------------------------------------------------
# Seed helpers — multi-leg
# ---------------------------------------------------------------------------


def _seed_two_leg_run(
    session,
    *,
    risk_overrides=None,
    leg1_position="B",
    leg2_position="B",
):
    """Seed strategy + 2 legs + 2 positions + IN_TRADE run.

    Both legs at avg_entry=1500, qty=50, on different symbols (INFY + TCS).
    Returns (sid, [leg1_id, leg2_id], rid, [pos1_id, pos2_id]).
    """
    from database.strategy_v2_db import (
        StrategyLeg, StrategyPosition, StrategyRiskConfig,
        StrategyRun, StrategyV2,
    )

    s = StrategyV2(
        name="Test", webhook_id="t", user_id="tester",
        is_intraday=True, start_time="09:15", end_time="15:30",
        state="ARMED", is_active=True, mode="live",
        webhook_signing_method="NONE",
    )
    session.add(s)
    session.flush()

    # Risk config row (Phase 4)
    rc = StrategyRiskConfig(strategy_id=s.id)
    if risk_overrides:
        for k, v in risk_overrides.items():
            setattr(rc, k, v)
    session.add(rc)
    session.flush()

    legs = []
    positions = []
    for i, (sym, pos_side) in enumerate(
        ((("INFY", leg1_position), ("TCS", leg2_position)))[:2]
    ):
        symbol, position = sym, pos_side
        leg = StrategyLeg(
            strategy_id=s.id, leg_index=i + 1, segment="CASH",
            position=position, product="MIS",
            symbol_cash=symbol, qty=50,
            sl_enabled=False, target_enabled=False, trail_enabled=False,
            resolved_symbol=symbol, resolved_exchange="NSE",
            lot_size_cache=1, tick_size_cache=Decimal("0.05"),
        )
        session.add(leg)
        session.flush()
        legs.append(leg.id)

    run = StrategyRun(strategy_id=s.id, state="IN_TRADE", mode="live")
    session.add(run)
    session.flush()

    for leg_id, sym, position in zip(
        legs, ("INFY", "TCS"), (leg1_position, leg2_position)
    ):
        net_qty = 50 if position == "B" else -50
        pos = StrategyPosition(
            strategy_id=s.id, run_id=run.id, leg_id=leg_id,
            symbol=sym, exchange="NSE", product="MIS",
            net_qty=net_qty, avg_entry=Decimal("1500"),
            quantity=str(net_qty),
            average_price="1500", ltp="1500", pnl="0",
            leg_state="OPEN",
            last_trail_anchor=Decimal("1500"),
        )
        session.add(pos)
        session.flush()
        positions.append(pos.id)

    session.commit()
    return s.id, legs, run.id, positions


def _tick(symbol, exchange, ltp):
    return {
        "symbol": symbol, "exchange": exchange, "mode": 1,
        "data": {"ltp": ltp},
    }


# ---------------------------------------------------------------------------
# Aggregate MTM + Overall SL
# ---------------------------------------------------------------------------


def test_overall_sl_fires_strategy_exit(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    """Two long legs at 1500. Overall SL = ₹500. A 5pt drop on each leg
    yields aggregate MTM = -500, triggers overall SL."""
    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "overall_sl_enabled": True,
            "overall_sl_abs": Decimal("500"),
        },
    )
    clean_engine.register_run(rid)

    # First tick — INFY drops 5pt → leg1 mtm = -250, leg2 still 0 → agg = -250
    clean_engine._on_tick(_tick("INFY", "NSE", 1495.0))
    assert fake_exit_strategy == []  # not yet hit

    # Second tick — TCS drops 5pt → leg2 mtm = -250 → agg = -500 → trigger
    clean_engine._on_tick(_tick("TCS", "NSE", 1495.0))
    assert fake_exit_strategy
    assert fake_exit_strategy[0]["run_id"] == rid
    assert fake_exit_strategy[0]["reason"] == "exit_overall_sl"


def test_overall_target_fires(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "overall_target_enabled": True,
            "overall_target_abs": Decimal("500"),
        },
    )
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick("INFY", "NSE", 1505.0))
    clean_engine._on_tick(_tick("TCS", "NSE", 1505.0))
    assert fake_exit_strategy
    assert fake_exit_strategy[0]["reason"] == "exit_overall_target"


def test_overall_sl_short_legs(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    """Short legs: adverse = price RISES."""
    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "overall_sl_enabled": True,
            "overall_sl_abs": Decimal("500"),
        },
        leg1_position="S",
        leg2_position="S",
    )
    clean_engine.register_run(rid)

    # Short leg loses when price rises. 5pt rise on each → agg = -500
    clean_engine._on_tick(_tick("INFY", "NSE", 1505.0))
    clean_engine._on_tick(_tick("TCS", "NSE", 1505.0))
    assert fake_exit_strategy
    assert fake_exit_strategy[0]["reason"] == "exit_overall_sl"


# ---------------------------------------------------------------------------
# Profit lock
# ---------------------------------------------------------------------------


def test_profit_lock_arms_at_peak(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    """lock_at=600, lock_min=300. Peak hits 700 → arm. Drop to 300 → exit."""
    from database.strategy_v2_db import StrategyRun

    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "lock_profit_enabled": True,
            "lock_at_abs": Decimal("600"),
            "lock_min_abs": Decimal("300"),
        },
    )
    clean_engine.register_run(rid)

    # Drive peak: each leg up 7pt → agg = +700
    clean_engine._on_tick(_tick("INFY", "NSE", 1507.0))
    clean_engine._on_tick(_tick("TCS", "NSE", 1507.0))

    # Engine should have armed the lock
    run_row = in_memory_db.query(StrategyRun).filter(StrategyRun.id == rid).first()
    assert run_row.profit_locked is True
    assert float(run_row.peak_mtm) == 700.0
    assert fake_exit_strategy == []  # not floor-hit yet

    # Retrace: each leg back down → agg drops to 300 → floor hit
    clean_engine._on_tick(_tick("INFY", "NSE", 1503.0))
    clean_engine._on_tick(_tick("TCS", "NSE", 1503.0))
    assert fake_exit_strategy
    assert fake_exit_strategy[0]["reason"] == "exit_profit_lock"


def test_profit_lock_no_floor_until_armed(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    """Floor at +300 does NOT trigger before peak crosses lock_at."""
    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "lock_profit_enabled": True,
            "lock_at_abs": Decimal("600"),
            "lock_min_abs": Decimal("300"),
        },
    )
    clean_engine.register_run(rid)

    # Peak only reaches 400 — below lock_at — lock never arms.
    clean_engine._on_tick(_tick("INFY", "NSE", 1504.0))
    clean_engine._on_tick(_tick("TCS", "NSE", 1504.0))
    # Drop to ₹300 — floor would trigger IF armed, but it isn't.
    clean_engine._on_tick(_tick("INFY", "NSE", 1503.0))
    clean_engine._on_tick(_tick("TCS", "NSE", 1503.0))
    assert fake_exit_strategy == []


# ---------------------------------------------------------------------------
# Trail-to-entry
# ---------------------------------------------------------------------------


def test_trail_to_entry_arms_and_pins_sl(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    """Trail-to-entry threshold = 1pct (15pts on 1500). After 15pt favorable
    move, the leg's SL is pinned to entry."""
    from database.strategy_v2_db import StrategyPosition

    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "trail_to_entry_enabled": True,
            "trail_to_entry_threshold": Decimal("1"),
            "trail_to_entry_unit": "pct",
        },
    )
    clean_engine.register_run(rid)

    # 15pt favorable on INFY → arm; SL pinned to 1500
    clean_engine._on_tick(_tick("INFY", "NSE", 1515.0))
    pos = in_memory_db.query(StrategyPosition).filter(
        StrategyPosition.id == pids[0]
    ).first()
    assert pos.trail_to_entry_armed is True
    assert float(pos.current_sl_price) == 1500.0


def test_trail_to_entry_below_threshold_no_arm(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    from database.strategy_v2_db import StrategyPosition

    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "trail_to_entry_enabled": True,
            "trail_to_entry_threshold": Decimal("1"),
            "trail_to_entry_unit": "pct",
        },
    )
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick("INFY", "NSE", 1510.0))  # only 10pt move
    pos = in_memory_db.query(StrategyPosition).filter(
        StrategyPosition.id == pids[0]
    ).first()
    assert pos.trail_to_entry_armed is False


def test_trail_to_entry_one_way_per_leg(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    """Once armed, the latch stays — even if price moves further favorably,
    the SL doesn't re-pin (it stays at entry)."""
    from database.strategy_v2_db import StrategyPosition

    sid, lids, rid, pids = _seed_two_leg_run(
        in_memory_db,
        risk_overrides={
            "trail_to_entry_enabled": True,
            "trail_to_entry_threshold": Decimal("1"),
            "trail_to_entry_unit": "pct",
        },
    )
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick("INFY", "NSE", 1515.0))  # arm
    clean_engine._on_tick(_tick("INFY", "NSE", 1530.0))  # further favorable

    pos = in_memory_db.query(StrategyPosition).filter(
        StrategyPosition.id == pids[0]
    ).first()
    # SL stayed pinned at entry (not advanced — that's leg-trail's job)
    assert float(pos.current_sl_price) == 1500.0
    assert pos.trail_to_entry_armed is True


# ---------------------------------------------------------------------------
# Peak persistence
# ---------------------------------------------------------------------------


def test_peak_mtm_persists_to_strategy_runs(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    from database.strategy_v2_db import StrategyRun

    sid, lids, rid, pids = _seed_two_leg_run(in_memory_db)
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick("INFY", "NSE", 1510.0))  # +500 on leg1
    clean_engine._on_tick(_tick("TCS", "NSE", 1510.0))  # +500 on leg2 → agg 1000

    run = in_memory_db.query(StrategyRun).filter(StrategyRun.id == rid).first()
    assert float(run.peak_mtm) == 1000.0


def test_peak_only_ratchets_up(
    in_memory_db, clean_engine, fake_mds, fake_exit_strategy, fake_close_leg,
):
    """Drawdowns never reduce peak_mtm."""
    from database.strategy_v2_db import StrategyRun

    sid, lids, rid, pids = _seed_two_leg_run(in_memory_db)
    clean_engine.register_run(rid)

    clean_engine._on_tick(_tick("INFY", "NSE", 1510.0))  # +500
    clean_engine._on_tick(_tick("TCS", "NSE", 1510.0))   # +500 → agg=+1000
    clean_engine._on_tick(_tick("INFY", "NSE", 1490.0))  # leg1 -500 → agg=0

    run = in_memory_db.query(StrategyRun).filter(StrategyRun.id == rid).first()
    assert float(run.peak_mtm) == 1000.0  # NOT 0 — ratchet preserves peak
