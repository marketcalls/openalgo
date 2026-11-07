# test/test_pnl_tag_by_order.py
"""Tagging one fill sets the strategy on every fill of the same order.

One order is filled in many pieces, each its own row in tradebook_fills.
set_trade_strategy (services/pnl_history_service.py) must carry the tag to
all of them, and only them: not another order, not another symbol, and not
a row with no order id.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

import services.pnl_history_service as svc
from database.pnl_db import TradebookFill


@pytest.fixture
def session(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    TradebookFill.__table__.create(engine)
    scoped = scoped_session(sessionmaker(bind=engine, autoflush=False))
    monkeypatch.setattr(svc, "db_session", scoped)
    monkeypatch.setattr(svc, "get_auth_token_broker", lambda api_key: ("token", "zerodha"))
    yield scoped
    engine.dispose()


def _fill(n, orderid, symbol="CYIENT", strategy=None):
    return TradebookFill(
        dedup_key=f"k{n}",
        tradeid=f"t{n}",
        orderid=orderid,
        symbol=symbol,
        exchange="NSE",
        product="CNC",
        action="BUY",
        quantity=10,
        average_price=100.0,
        trade_value=1000.0,
        trade_timestamp=datetime(2026, 9, 30, 15, 13, 35),
        source="capture",
        strategy=strategy,
    )


def _strategies(session):
    session.expire_all()
    return {r.dedup_key: r.strategy for r in session.query(TradebookFill).all()}


def test_tag_reaches_every_fill_of_the_order_and_no_other(session):
    session.add_all(
        [
            _fill(1, "O1"),
            _fill(2, "O1"),
            _fill(3, "O1", strategy="Old"),  # overwritten, same as the single-row rule
            _fill(4, "O2"),  # another order
            _fill(5, "O1", symbol="OTHER"),  # same order id, other symbol
            _fill(6, None),  # no order id: nothing to group on
        ]
    )
    session.commit()

    ok, body, status = svc.set_trade_strategy("key", 1, "EquityBreakoutPositional")

    assert ok and status == 200
    assert sorted(body["data"]["updated_ids"]) == [1, 2, 3]
    assert body["data"]["strategy"] == "EquityBreakoutPositional"
    assert _strategies(session) == {
        "k1": "EquityBreakoutPositional",
        "k2": "EquityBreakoutPositional",
        "k3": "EquityBreakoutPositional",
        "k4": None,
        "k5": None,
        "k6": None,
    }


def test_fill_without_order_id_tags_only_itself(session):
    session.add_all([_fill(1, None), _fill(2, None)])
    session.commit()

    ok, body, _ = svc.set_trade_strategy("key", 1, "Manual")

    assert ok
    assert body["data"]["updated_ids"] == [1]
    assert _strategies(session) == {"k1": "Manual", "k2": None}


def test_unknown_trade_is_404(session):
    ok, _, status = svc.set_trade_strategy("key", 999, "X")
    assert not ok and status == 404
