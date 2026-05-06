"""Phase 2 — position tracker tests.

Validates the fill-reconciliation math in services/strategy/position_tracker:
  - net_qty (BUY -> +qty, SELL -> -qty, sum across trades)
  - avg_entry (weighted average over the dominant-side trades)
  - realized_pnl (closed-qty * (sell_avg - buy_avg))
  - leg_state transitions (PENDING_ENTRY -> OPEN, flat -> CLOSED)
  - idempotency on duplicate broker pushes (orderid already recorded)

Uses an in-memory SQLAlchemy engine (sqlite:///:memory:) so tests don't touch
db/openalgo.db. The strategy_v2_db module's engine + session are swapped via
monkeypatch before any function under test runs.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def in_memory_db(monkeypatch):
    """Spin up an in-memory SQLite, point strategy_v2_db at it, create tables.

    StaticPool is fine for a single-thread test (the production warning about
    StaticPool applies to multi-threaded request handling, not unit tests).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

    from database import strategy_v2_db

    monkeypatch.setattr(strategy_v2_db, "engine", engine)
    monkeypatch.setattr(strategy_v2_db, "db_session", Session)
    # The position tracker imports db_session at module load time, so we patch
    # there too — by attribute, since position_tracker has its own reference.
    from services.strategy import position_tracker as pt
    monkeypatch.setattr(pt, "db_session", Session)

    strategy_v2_db.Base.metadata.create_all(bind=engine)
    yield Session
    Session.remove()
    engine.dispose()


def _seed_order(session, **overrides):
    from database.strategy_v2_db import StrategyOrder

    defaults = dict(
        strategy_id=1, run_id=1, leg_id=1,
        action="BUY", symbol="INFY", exchange="NSE",
        orderid="OID1", product="MIS", quantity="50",
        price=0, pricetype="MARKET", order_status="open",
        trigger_price=0, source="entry", mode="live",
    )
    defaults.update(overrides)
    o = StrategyOrder(**defaults)
    session.add(o)
    session.commit()
    return o


def _broker_event(orderid="OID1", status="complete", filled_qty=50, avg_price=1500.0):
    return SimpleNamespace(
        orderid=orderid,
        status=status,
        filled_qty=filled_qty,
        average_price=avg_price,
    )


# ----------------------------------------------------------------------------
# on_broker_order_update — single fill
# ----------------------------------------------------------------------------


def test_single_buy_fill_creates_position(in_memory_db):
    from database.strategy_v2_db import StrategyPosition, StrategyTrade
    from services.strategy import position_tracker

    _seed_order(in_memory_db)
    position_tracker.on_broker_order_update(_broker_event())

    trades = in_memory_db.query(StrategyTrade).all()
    assert len(trades) == 1
    assert int(trades[0].quantity) == 50

    positions = in_memory_db.query(StrategyPosition).all()
    assert len(positions) == 1
    p = positions[0]
    assert p.net_qty == 50
    assert float(p.avg_entry) == 1500.0
    assert p.leg_state == "OPEN"
    assert float(p.realized_pnl) == 0


def test_buy_then_sell_closes_position(in_memory_db):
    from database.strategy_v2_db import StrategyOrder, StrategyPosition
    from services.strategy import position_tracker

    _seed_order(in_memory_db, orderid="BUY1")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="BUY1", filled_qty=50, avg_price=1500.0)
    )

    _seed_order(in_memory_db, orderid="SELL1", action="SELL", strategy_id=1)
    position_tracker.on_broker_order_update(
        _broker_event(orderid="SELL1", filled_qty=50, avg_price=1520.0)
    )

    positions = in_memory_db.query(StrategyPosition).all()
    assert len(positions) == 1
    p = positions[0]
    assert p.net_qty == 0
    assert p.leg_state == "CLOSED"
    # P&L = (1520 - 1500) * 50 = 1000
    assert float(p.realized_pnl) == 1000.0


def test_short_then_cover_realized_pnl(in_memory_db):
    """SELL first, BUY back — realized P&L is positive when cover < entry."""
    from database.strategy_v2_db import StrategyPosition
    from services.strategy import position_tracker

    _seed_order(in_memory_db, orderid="SELL1", action="SELL")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="SELL1", filled_qty=50, avg_price=1500.0)
    )

    _seed_order(in_memory_db, orderid="BUY1", action="BUY")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="BUY1", filled_qty=50, avg_price=1480.0)
    )

    p = in_memory_db.query(StrategyPosition).one()
    assert p.net_qty == 0
    # short P&L = (sell - buy) * closed_qty = (1500 - 1480) * 50 = 1000
    assert float(p.realized_pnl) == 1000.0


def test_partial_close_keeps_position_open(in_memory_db):
    from database.strategy_v2_db import StrategyPosition
    from services.strategy import position_tracker

    _seed_order(in_memory_db, orderid="BUY1")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="BUY1", filled_qty=100, avg_price=1500.0)
    )
    _seed_order(in_memory_db, orderid="SELL1", action="SELL")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="SELL1", filled_qty=40, avg_price=1520.0)
    )

    p = in_memory_db.query(StrategyPosition).one()
    assert p.net_qty == 60
    assert p.leg_state == "OPEN"
    # Realized = (1520 - 1500) * 40 = 800 (only the closed 40-qty portion)
    assert float(p.realized_pnl) == 800.0


# ----------------------------------------------------------------------------
# Idempotency — duplicate broker pushes for the same orderid
# ----------------------------------------------------------------------------


def test_duplicate_broker_update_is_idempotent(in_memory_db):
    from database.strategy_v2_db import StrategyPosition, StrategyTrade
    from services.strategy import position_tracker

    _seed_order(in_memory_db)
    position_tracker.on_broker_order_update(_broker_event())
    position_tracker.on_broker_order_update(_broker_event())  # again
    position_tracker.on_broker_order_update(_broker_event())  # and again

    assert in_memory_db.query(StrategyTrade).count() == 1
    p = in_memory_db.query(StrategyPosition).one()
    assert p.net_qty == 50  # not 150


# ----------------------------------------------------------------------------
# Status updates without fills (cancellation, rejection, open)
# ----------------------------------------------------------------------------


def test_open_status_updates_strategy_orders_only(in_memory_db):
    from database.strategy_v2_db import StrategyOrder, StrategyPosition, StrategyTrade
    from services.strategy import position_tracker

    _seed_order(in_memory_db)
    position_tracker.on_broker_order_update(
        _broker_event(status="open", filled_qty=0)
    )
    o = in_memory_db.query(StrategyOrder).one()
    assert o.order_status == "open"
    assert in_memory_db.query(StrategyTrade).count() == 0
    assert in_memory_db.query(StrategyPosition).count() == 0


def test_unknown_orderid_is_no_op(in_memory_db):
    from database.strategy_v2_db import StrategyTrade
    from services.strategy import position_tracker

    # No order seeded — this orderid isn't a strategy order at all.
    position_tracker.on_broker_order_update(_broker_event(orderid="GLOBAL_MANUAL"))
    assert in_memory_db.query(StrategyTrade).count() == 0


# ----------------------------------------------------------------------------
# OrderEvent reuse paths
# ----------------------------------------------------------------------------


def test_on_order_placed_marks_strategy_order_open(in_memory_db):
    from database.strategy_v2_db import StrategyOrder
    from services.strategy import position_tracker

    _seed_order(in_memory_db, order_status="pending")
    event = SimpleNamespace(orderid="OID1", symbol="INFY", exchange="NSE")
    position_tracker.on_order_placed(event)

    o = in_memory_db.query(StrategyOrder).one()
    assert o.order_status == "open"
    assert o.last_status_update_at is not None


def test_on_order_cancelled_updates_status(in_memory_db):
    from database.strategy_v2_db import StrategyOrder
    from services.strategy import position_tracker

    _seed_order(in_memory_db, order_status="open")
    event = SimpleNamespace(orderid="OID1")
    position_tracker.on_order_cancelled(event)

    o = in_memory_db.query(StrategyOrder).one()
    assert o.order_status == "cancelled"


# ----------------------------------------------------------------------------
# Multi-leg strategies — separate positions per leg
# ----------------------------------------------------------------------------


def test_two_legs_track_independently(in_memory_db):
    from database.strategy_v2_db import StrategyPosition
    from services.strategy import position_tracker

    _seed_order(in_memory_db, leg_id=1, orderid="LEG1_BUY")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="LEG1_BUY", filled_qty=50, avg_price=1500.0)
    )
    _seed_order(in_memory_db, leg_id=2, orderid="LEG2_BUY", symbol="TCS")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="LEG2_BUY", filled_qty=25, avg_price=3500.0)
    )

    positions = in_memory_db.query(StrategyPosition).order_by(StrategyPosition.leg_id).all()
    assert len(positions) == 2
    assert positions[0].leg_id == 1 and positions[0].net_qty == 50
    assert positions[1].leg_id == 2 and positions[1].net_qty == 25


# ----------------------------------------------------------------------------
# Strategy-without-leg orders (manual/cleanup) — no position aggregation
# ----------------------------------------------------------------------------


def test_orders_without_leg_id_dont_create_positions(in_memory_db):
    from database.strategy_v2_db import StrategyPosition, StrategyTrade
    from services.strategy import position_tracker

    _seed_order(in_memory_db, leg_id=None, orderid="MANUAL1")
    position_tracker.on_broker_order_update(
        _broker_event(orderid="MANUAL1", filled_qty=10, avg_price=100)
    )

    # Trade row is still recorded for audit, but no position aggregation.
    assert in_memory_db.query(StrategyTrade).count() == 1
    assert in_memory_db.query(StrategyPosition).count() == 0
