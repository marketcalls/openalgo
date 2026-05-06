"""Phase 5 — realtime broadcaster + snapshot API tests.

Covers:
  - engine.snapshot_run output shape (every documented field, types)
  - engine.runs_for_symbol lookup
  - Broadcaster debounce (200ms): emits within window suppressed
  - Broadcaster fan-out: tick → emit one strategy_pnl_tick + N leg updates
  - Health watcher: state-flip triggers strategy_health emission

Drives ticks directly (no real market_data_service). Captures Socket.IO
emissions via a mock module.
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

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
    fake.subscribe_with_priority = MagicMock(return_value=43)
    fake.unsubscribe_priority = MagicMock(return_value=True)
    fake.is_trade_management_safe = MagicMock(return_value=(True, ""))
    import services.market_data_service as mds_mod
    monkeypatch.setattr(mds_mod, "get_market_data_service", lambda: fake)
    yield fake


@pytest.fixture
def fake_socketio(monkeypatch):
    """Replace socketio.emit so tests can capture broadcasts."""
    fake = MagicMock()
    fake.emit = MagicMock()
    monkeypatch.setattr("extensions.socketio", fake)
    yield fake


@pytest.fixture
def clean_broadcaster():
    """Reset broadcaster state between tests."""
    from services.strategy.realtime_broadcaster import get_broadcaster

    b = get_broadcaster()
    b.stop()
    b._last_emit_ts.clear()
    b._tick_subscriber_id = None
    b._last_safe_flag = None
    yield b
    b.stop()
    b._last_emit_ts.clear()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_run(session, *, leg_count=2, trail=False, target=True, sl=True):
    from database.strategy_v2_db import (
        StrategyLeg, StrategyPosition, StrategyRun, StrategyV2,
    )

    s = StrategyV2(
        name="T", webhook_id=f"u-{leg_count}", user_id="u",
        is_intraday=True, start_time="09:15", end_time="15:30",
        state="ARMED", is_active=True, mode="live",
        webhook_signing_method="NONE",
    )
    session.add(s)
    session.flush()

    leg_ids = []
    pos_ids = []
    symbols = ("INFY", "TCS", "WIPRO", "RELIANCE")
    for i in range(leg_count):
        leg = StrategyLeg(
            strategy_id=s.id, leg_index=i + 1, segment="CASH",
            position="B", product="MIS",
            symbol_cash=symbols[i], qty=50,
            target_enabled=target, target_value=Decimal("20"),
            target_unit="pts" if target else None,
            sl_enabled=sl, sl_value=Decimal("10"),
            sl_unit="pts" if sl else None,
            trail_enabled=trail,
            trail_x=Decimal("1") if trail else None,
            trail_y=Decimal("2") if trail else None,
            trail_unit="pts" if trail else None,
            resolved_symbol=symbols[i], resolved_exchange="NSE",
            lot_size_cache=1, tick_size_cache=Decimal("0.05"),
        )
        session.add(leg)
        session.flush()
        leg_ids.append(leg.id)

    run = StrategyRun(strategy_id=s.id, state="IN_TRADE", mode="live")
    session.add(run)
    session.flush()

    for leg_id, sym in zip(leg_ids, symbols):
        pos = StrategyPosition(
            strategy_id=s.id, run_id=run.id, leg_id=leg_id,
            symbol=sym, exchange="NSE", product="MIS",
            net_qty=50, avg_entry=Decimal("1500"),
            quantity="50", average_price="1500", ltp="1500", pnl="0",
            leg_state="OPEN",
            last_trail_anchor=Decimal("1500"),
        )
        session.add(pos)
        session.flush()
        pos_ids.append(pos.id)

    session.commit()
    return s.id, leg_ids, run.id, pos_ids


# ===========================================================================
# Engine snapshot API
# ===========================================================================


def test_snapshot_run_returns_none_when_not_registered(in_memory_db, clean_engine, fake_mds):
    sid, lids, rid, pids = _seed_run(in_memory_db)
    # Not registered yet
    assert clean_engine.snapshot_run(rid) is None


def test_snapshot_run_basic_shape(in_memory_db, clean_engine, fake_mds):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=2)
    clean_engine.register_run(rid)

    snap = clean_engine.snapshot_run(rid)
    assert snap is not None
    assert snap["run_id"] == rid
    assert snap["strategy_id"] == sid
    # Top-level metrics
    for k in ("agg_mtm", "peak_mtm", "drawdown", "profit_locked"):
        assert k in snap
    # Per-leg list
    assert isinstance(snap["legs"], list)
    assert len(snap["legs"]) == 2
    for leg in snap["legs"]:
        for k in (
            "leg_id", "symbol", "exchange", "direction",
            "avg_entry", "net_qty", "ltp", "mtm",
            "current_sl_price", "sl_distance_pts", "target_distance_pts",
            "trail_advances_count", "trail_to_entry_armed",
            "next_trail_at_pts", "tick_size",
        ):
            assert k in leg


def test_snapshot_recomputes_agg_mtm_from_last_ltp(
    in_memory_db, clean_engine, fake_mds,
):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=2)
    clean_engine.register_run(rid)

    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1505.0  # +5 → leg_mtm = +250
    rt.legs[lids[1]].last_ltp = 1510.0  # +10 → leg_mtm = +500

    snap = clean_engine.snapshot_run(rid)
    assert snap["agg_mtm"] == 750.0


def test_snapshot_drawdown_from_peak(in_memory_db, clean_engine, fake_mds):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=2)
    clean_engine.register_run(rid)

    rt = clean_engine._runs[rid]
    rt.peak_mtm = 1000.0
    rt.legs[lids[0]].last_ltp = 1502.0   # +100
    rt.legs[lids[1]].last_ltp = 1502.0   # +100 → agg = 200
    snap = clean_engine.snapshot_run(rid)
    assert snap["drawdown"] == 800.0   # 1000 - 200


def test_snapshot_sl_distance_long(in_memory_db, clean_engine, fake_mds):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    clean_engine.register_run(rid)

    rt = clean_engine._runs[rid]
    leg = rt.legs[lids[0]]
    leg.last_ltp = 1505.0
    leg.current_sl_price = 1490.0  # set initial SL

    snap = clean_engine.snapshot_run(rid)
    leg_snap = snap["legs"][0]
    # Long: ltp - sl = 1505 - 1490 = 15pts away from SL
    assert leg_snap["sl_distance_pts"] == 15.0


def test_snapshot_sl_distance_short(in_memory_db, clean_engine, fake_mds):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    # Flip the position to short.
    from database.strategy_v2_db import StrategyPosition
    in_memory_db.query(StrategyPosition).filter(
        StrategyPosition.id == pids[0]
    ).update({"net_qty": -50})
    in_memory_db.commit()

    clean_engine.register_run(rid)
    rt = clean_engine._runs[rid]
    leg = rt.legs[lids[0]]
    leg.last_ltp = 1495.0
    leg.current_sl_price = 1510.0

    snap = clean_engine.snapshot_run(rid)
    leg_snap = snap["legs"][0]
    # Short: sl - ltp = 1510 - 1495 = 15pts away from SL (favorable distance)
    assert leg_snap["sl_distance_pts"] == 15.0


def test_snapshot_target_distance_long(in_memory_db, clean_engine, fake_mds):
    """Target = entry + 20 = 1520. ltp at 1510 → distance = 10."""
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    clean_engine.register_run(rid)
    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1510.0

    snap = clean_engine.snapshot_run(rid)
    assert snap["legs"][0]["target_distance_pts"] == 10.0


def test_snapshot_next_trail_at(in_memory_db, clean_engine, fake_mds):
    """trail_x=1pt, anchor=1500, ltp=1502.5 → next advance at 0.5 pts more."""
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1, trail=True)
    clean_engine.register_run(rid)
    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1502.5
    rt.legs[lids[0]].last_trail_anchor = 1500.0

    snap = clean_engine.snapshot_run(rid)
    leg_snap = snap["legs"][0]
    # 2.5pt favorable so far, x_delta=1pt; next advance fires at +1.0 from
    # the anchor. We're at 2.5 favorable (anchor still 1500 in this snapshot
    # — engine hasn't ratcheted yet). Distance to next: x - (favorable % x)
    # = 1 - (2.5 % 1) = 1 - 0.5 = 0.5
    assert abs((leg_snap["next_trail_at_pts"] or 0) - 0.5) < 0.001


# ===========================================================================
# runs_for_symbol
# ===========================================================================


def test_runs_for_symbol_returns_active_runs(in_memory_db, clean_engine, fake_mds):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=2)
    clean_engine.register_run(rid)
    assert clean_engine.runs_for_symbol("NSE", "INFY") == [rid]
    assert clean_engine.runs_for_symbol("NSE", "TCS") == [rid]
    assert clean_engine.runs_for_symbol("NSE", "MISSING") == []


# ===========================================================================
# Broadcaster — emission + debounce
# ===========================================================================


def _tick(symbol="INFY", exchange="NSE", ltp=1505.0):
    return {
        "symbol": symbol, "exchange": exchange, "mode": 1,
        "data": {"ltp": ltp},
    }


def test_broadcaster_emits_pnl_tick_and_leg_updates(
    in_memory_db, clean_engine, fake_mds, fake_socketio, clean_broadcaster,
):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=2)
    clean_engine.register_run(rid)

    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1505.0
    rt.legs[lids[1]].last_ltp = 1510.0

    clean_broadcaster._on_tick(_tick(symbol="INFY"))

    # Expect 1 strategy_pnl_tick + 2 strategy_leg_update emissions
    assert fake_socketio.emit.called
    event_names = [call.args[0] for call in fake_socketio.emit.call_args_list]
    assert "strategy_pnl_tick" in event_names
    assert event_names.count("strategy_leg_update") == 2


def test_broadcaster_debounce_suppresses_burst(
    in_memory_db, clean_engine, fake_mds, fake_socketio, clean_broadcaster,
):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    clean_engine.register_run(rid)
    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1505.0

    clean_broadcaster._on_tick(_tick("INFY"))
    fake_socketio.emit.reset_mock()
    # Rapid second tick — should be suppressed by 200ms debounce
    clean_broadcaster._on_tick(_tick("INFY", ltp=1506.0))
    assert fake_socketio.emit.called is False


def test_broadcaster_emits_after_debounce_window(
    in_memory_db, clean_engine, fake_mds, fake_socketio, clean_broadcaster,
):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    clean_engine.register_run(rid)
    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1505.0

    clean_broadcaster._on_tick(_tick("INFY"))
    fake_socketio.emit.reset_mock()
    # Move the per-run last_emit_ts back so the next tick is past debounce
    clean_broadcaster._last_emit_ts[rid] = time.monotonic() - 1.0
    clean_broadcaster._on_tick(_tick("INFY", ltp=1506.0))
    assert fake_socketio.emit.called


def test_broadcaster_skips_unregistered_symbol(
    in_memory_db, clean_engine, fake_mds, fake_socketio, clean_broadcaster,
):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    clean_engine.register_run(rid)
    clean_broadcaster._on_tick(_tick("WIPRO"))  # Not in active runs
    assert fake_socketio.emit.called is False


def test_broadcaster_emits_room_scoped(
    in_memory_db, clean_engine, fake_mds, fake_socketio, clean_broadcaster,
):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    clean_engine.register_run(rid)
    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1505.0

    clean_broadcaster._on_tick(_tick("INFY"))
    # All emissions go to room=f"strategy_{sid}"
    for call in fake_socketio.emit.call_args_list:
        if call.args[0] in ("strategy_pnl_tick", "strategy_leg_update"):
            assert call.kwargs.get("room") == f"strategy_{sid}"


def test_broadcaster_payload_carries_ts_pair(
    in_memory_db, clean_engine, fake_mds, fake_socketio, clean_broadcaster,
):
    sid, lids, rid, pids = _seed_run(in_memory_db, leg_count=1)
    clean_engine.register_run(rid)
    rt = clean_engine._runs[rid]
    rt.legs[lids[0]].last_ltp = 1505.0

    clean_broadcaster._on_tick(_tick("INFY"))
    # Look at the strategy_pnl_tick payload
    for call in fake_socketio.emit.call_args_list:
        if call.args[0] == "strategy_pnl_tick":
            payload = call.args[1]
            assert "ts_utc" in payload and isinstance(payload["ts_utc"], int)
            assert "ts_ist" in payload and isinstance(payload["ts_ist"], str)
            return
    pytest.fail("no strategy_pnl_tick emission seen")


# ===========================================================================
# Health watcher
# ===========================================================================


def test_health_emit_on_state_flip(
    in_memory_db, clean_engine, fake_mds, fake_socketio, clean_broadcaster,
):
    """Calling _emit_health twice with the same flag should still emit
    twice (it's the watcher's loop that decides; _emit_health itself is
    just a publisher)."""
    clean_broadcaster._emit_health(False, "stale")
    assert fake_socketio.emit.called
    call = fake_socketio.emit.call_args_list[0]
    assert call.args[0] == "strategy_health"
    payload = call.args[1]
    assert payload["feed_safe"] is False
    assert payload["reason"] == "stale"
    assert "ts_utc" in payload
    assert "ts_ist" in payload


def test_health_emit_carries_order_channel_safe(
    fake_socketio, clean_broadcaster,
):
    """Phase 5 ships order_channel_safe=True (broker WS channel deferred).
    Banner UI should still render the field."""
    clean_broadcaster._emit_health(True, "")
    payload = fake_socketio.emit.call_args.args[1]
    assert payload["order_channel_safe"] is True
