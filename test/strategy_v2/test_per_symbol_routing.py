"""Phase 13 — per-symbol routing + EXITING->CLOSED transition tests.

Pure-function tests of services.strategy.ingestion_service._route_for_segment
and services.strategy.position_tracker._maybe_close_run. No HTTP, no DB
writes against the production engine — uses SimpleNamespace shims for
the strategy / leg / run inputs and a real in-memory SQLite session
for _maybe_close_run since it queries the DB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool


# ===========================================================================
# _route_for_segment — pure logic, no DB
# ===========================================================================


def _strategy(*, segment="CASH", trading_mode="LONG", legs=()):
    return SimpleNamespace(segment=segment, trading_mode=trading_mode, legs=list(legs))


def _leg(leg_id, symbol):
    return SimpleNamespace(id=leg_id, segment="CASH", symbol_cash=symbol)


def test_route_fno_pack_ignores_payload():
    """F&O strategies fire all legs together; symbol/action are not
    consulted for routing."""
    from services.strategy.ingestion_service import _route_for_segment

    s = _strategy(segment="INDEX_FO")
    intent, target = _route_for_segment(s, {})
    assert intent == "entry"
    assert target is None

    intent, target = _route_for_segment(
        s, {"symbol": "anything", "action": "something_weird"}
    )
    assert intent == "entry"
    assert target is None


def test_route_cash_long_buy_is_entry():
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="LONG", legs=[leg])
    intent, target = _route_for_segment(s, {"symbol": "RELIANCE", "action": "BUY"})
    assert intent == "entry"
    assert target is leg


def test_route_cash_long_sell_is_exit():
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="LONG", legs=[leg])
    intent, target = _route_for_segment(s, {"symbol": "RELIANCE", "action": "SELL"})
    assert intent == "exit"
    assert target is leg


def test_route_cash_short_inverts():
    """SHORT mode: SELL=entry, BUY=exit."""
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="SHORT", legs=[leg])

    intent, target = _route_for_segment(s, {"symbol": "RELIANCE", "action": "SELL"})
    assert intent == "entry"
    intent, target = _route_for_segment(s, {"symbol": "RELIANCE", "action": "BUY"})
    assert intent == "exit"


def test_route_cash_both_uses_position_size():
    """BOTH: position_size>0 = entry; =0 = exit."""
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="BOTH", legs=[leg])

    # position_size > 0 -> entry (regardless of BUY/SELL direction)
    intent, _ = _route_for_segment(
        s, {"symbol": "RELIANCE", "action": "BUY", "position_size": "1"}
    )
    assert intent == "entry"
    intent, _ = _route_for_segment(
        s, {"symbol": "RELIANCE", "action": "SELL", "position_size": "5"}
    )
    assert intent == "entry"

    # position_size = 0 -> exit
    intent, _ = _route_for_segment(
        s, {"symbol": "RELIANCE", "action": "SELL", "position_size": "0"}
    )
    assert intent == "exit"


def test_route_cash_both_requires_position_size():
    """BOTH webhook without position_size is rejected."""
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="BOTH", legs=[leg])
    routed = _route_for_segment(s, {"symbol": "RELIANCE", "action": "BUY"})
    assert routed[0] == "REJECT"
    assert routed[2] == "MISSING_POSITION_SIZE"


def test_route_cash_action_and_symbol_case_insensitive():
    """TradingView sends lowercase 'buy'/'sell'; symbols may also drift in
    case. Both must round-trip to the same routing decision."""
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="LONG", legs=[leg])

    for action in ("BUY", "buy", " Buy ", "bUy"):
        for symbol in ("RELIANCE", "reliance", " Reliance "):
            intent, target = _route_for_segment(
                s, {"symbol": symbol, "action": action}
            )
            assert intent == "entry", f"failed for action={action!r} symbol={symbol!r}"
            assert target is leg


def test_route_cash_unknown_symbol_rejected():
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="LONG", legs=[leg])
    routed = _route_for_segment(s, {"symbol": "GOOGL", "action": "BUY"})
    assert routed[0] == "REJECT"
    assert routed[2] == "UNKNOWN_SYMBOL"


def test_route_cash_missing_symbol_rejected():
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="LONG", legs=[leg])
    routed = _route_for_segment(s, {"action": "BUY"})
    assert routed[0] == "REJECT"
    assert routed[2] == "MISSING_SYMBOL"


def test_route_cash_bad_action_rejected():
    from services.strategy.ingestion_service import _route_for_segment

    leg = _leg(42, "RELIANCE")
    s = _strategy(trading_mode="LONG", legs=[leg])
    routed = _route_for_segment(s, {"symbol": "RELIANCE", "action": "HOLD"})
    assert routed[0] == "REJECT"
    assert routed[2] == "BAD_ACTION"


# ===========================================================================
# _maybe_close_run — DB-touching test against an in-memory SQLite
# ===========================================================================


@pytest.fixture
def in_memory_db(monkeypatch):
    """Fresh per-test SQLite + scoped session bound into the modules
    under test. Same pattern as test_rms_engine.py."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

    from database import strategy_v2_db

    monkeypatch.setattr(strategy_v2_db, "engine", engine)
    monkeypatch.setattr(strategy_v2_db, "db_session", Session)

    from services.strategy import position_tracker, state_machine

    monkeypatch.setattr(position_tracker, "db_session", Session)
    monkeypatch.setattr(state_machine, "db_session", Session)

    strategy_v2_db.Base.metadata.create_all(bind=engine)
    yield Session
    Session.remove()
    engine.dispose()


def _seed_run_with_position(
    session, *, run_state="EXITING", leg_state="OPEN", net_qty=1
):
    from database.strategy_v2_db import StrategyLeg, StrategyPosition, StrategyRun, StrategyV2

    s = StrategyV2(
        name="Test", webhook_id="test-uuid", user_id="tester",
        is_intraday=True, start_time="09:15", end_time="15:30",
        state="ARMED", is_active=True, mode="live",
        webhook_signing_method="NONE",
    )
    session.add(s)
    session.flush()
    leg = StrategyLeg(
        strategy_id=s.id, leg_index=1, segment="CASH",
        position="B", product="MIS", symbol_cash="RELIANCE", qty=1,
    )
    session.add(leg)
    session.flush()
    run = StrategyRun(
        strategy_id=s.id, leg_id=leg.id, state=run_state, mode="live",
        triggered_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    pos = StrategyPosition(
        strategy_id=s.id, run_id=run.id, leg_id=leg.id,
        symbol="RELIANCE", exchange="NSE", product="MIS",
        net_qty=net_qty, leg_state=leg_state,
        quantity=str(net_qty), average_price="1500", ltp="1500", pnl="0",
    )
    session.add(pos)
    session.commit()
    return run.id


def test_maybe_close_run_transitions_when_all_flat(in_memory_db):
    """All positions CLOSED + run in EXITING -> transition to CLOSED."""
    from services.strategy.position_tracker import _maybe_close_run
    from database.strategy_v2_db import StrategyRun

    run_id = _seed_run_with_position(
        in_memory_db, run_state="EXITING", leg_state="CLOSED", net_qty=0,
    )
    _maybe_close_run(run_id)
    in_memory_db.expire_all()
    run = in_memory_db.query(StrategyRun).filter_by(id=run_id).first()
    assert run.state == "CLOSED"
    assert run.exited_at is not None
    assert run.exit_reason  # auto-set if missing


def test_maybe_close_run_no_op_when_open_position(in_memory_db):
    """Position still OPEN -> run stays in EXITING."""
    from services.strategy.position_tracker import _maybe_close_run
    from database.strategy_v2_db import StrategyRun

    run_id = _seed_run_with_position(
        in_memory_db, run_state="EXITING", leg_state="OPEN", net_qty=1,
    )
    _maybe_close_run(run_id)
    in_memory_db.expire_all()
    run = in_memory_db.query(StrategyRun).filter_by(id=run_id).first()
    assert run.state == "EXITING"


def test_maybe_close_run_no_op_when_run_not_exiting(in_memory_db):
    """Run in IN_TRADE -> no transition (the helper is scoped to EXITING)."""
    from services.strategy.position_tracker import _maybe_close_run
    from database.strategy_v2_db import StrategyRun

    run_id = _seed_run_with_position(
        in_memory_db, run_state="IN_TRADE", leg_state="OPEN", net_qty=1,
    )
    _maybe_close_run(run_id)
    in_memory_db.expire_all()
    run = in_memory_db.query(StrategyRun).filter_by(id=run_id).first()
    assert run.state == "IN_TRADE"


def test_maybe_close_run_idempotent_after_close(in_memory_db):
    """Running _maybe_close_run on an already-CLOSED run is a no-op."""
    from services.strategy.position_tracker import _maybe_close_run
    from database.strategy_v2_db import StrategyRun

    run_id = _seed_run_with_position(
        in_memory_db, run_state="EXITING", leg_state="CLOSED", net_qty=0,
    )
    _maybe_close_run(run_id)  # first call -> CLOSED
    in_memory_db.expire_all()
    run_before = in_memory_db.query(StrategyRun).filter_by(id=run_id).first()
    state_after_first = run_before.state
    exited_at_after_first = run_before.exited_at

    _maybe_close_run(run_id)  # second call -> no-op
    in_memory_db.expire_all()
    run_after = in_memory_db.query(StrategyRun).filter_by(id=run_id).first()
    assert run_after.state == state_after_first == "CLOSED"
    assert run_after.exited_at == exited_at_after_first
