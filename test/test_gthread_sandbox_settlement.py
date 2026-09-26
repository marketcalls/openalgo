"""Settlement moves a position's money once (gthread audit trading-04, trading-05).

Expired contracts are settled from three places: every view of the position
book, the square-off job's minute sweep and the start-up catch-up. T+1 moves
CNC positions into holdings from the midnight job, from the catch-up on every
login (up to five devices) and from start-up and the analyzer toggle. Stale
MIS positions are settled by that same login catch-up. Each worked on the
positions it had loaded itself and moved money before closing the row, so two
of them settling one position released its margin and booked its P&L twice,
or folded it into the holding twice.

Each settlement now claims the position row first (a no-op UPDATE matched on
the quantity it read), lands the money and the row in one commit, and T+1 and
the catch-up sweep also run one at a time. The races below reproduce each
double settlement on the old code.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from decimal import Decimal

import pytest
from test_gthread_sandbox_support import (
    CAPITAL,
    funds_of,
    prepare_databases,
    release_sessions,
    reset_user,
    run_in_threads,
)

USER = "gthread_sandbox_settlement"
LONG_AGO = datetime(2020, 1, 1)


@pytest.fixture(autouse=True)
def fresh_account():
    prepare_databases()
    reset_user(USER)
    release_sessions()
    yield
    release_sessions()


class Rendezvous:
    """Let two racers meet, then let the first finish before the second goes on.

    The first caller waits (up to ``wait`` seconds) for a second one. Once both
    are there the second sleeps briefly, so the first commits its settlement
    before the second reads anything: on the old code the second then settles
    the same position again. With the fix the second caller never arrives,
    because it is held behind the first one's claim or lock, and the first
    simply goes on when its wait runs out.
    """

    def __init__(self, wait=2.0, lag=0.5):
        self.wait = wait
        self.lag = lag
        self.arrived = 0
        self.lock = threading.Lock()
        self.both = threading.Event()

    def __call__(self):
        with self.lock:
            self.arrived += 1
            me = self.arrived
        if me == 1:
            self.both.wait(self.wait)
        else:
            self.both.set()
            time.sleep(self.lag)


def _seed_position(symbol, exchange, product, quantity, average, ltp, margin, updated_at=None):
    from sqlalchemy import update

    from database.sandbox_db import SandboxPositions, db_session

    position = SandboxPositions(
        user_id=USER,
        symbol=symbol,
        exchange=exchange,
        product=product,
        quantity=quantity,
        average_price=Decimal(str(average)),
        ltp=Decimal(str(ltp)),
        pnl=Decimal("0.00"),
        pnl_percent=Decimal("0.00"),
        accumulated_realized_pnl=Decimal("0.00"),
        today_realized_pnl=Decimal("0.00"),
        margin_blocked=Decimal(str(margin)),
        created_at=LONG_AGO,
    )
    db_session.add(position)
    db_session.commit()
    if updated_at is not None:
        db_session.execute(
            update(SandboxPositions)
            .where(SandboxPositions.id == position.id)
            .values(updated_at=updated_at)
        )
        db_session.commit()
    position_id = position.id
    db_session.remove()
    return position_id


def _block(amount):
    from sandbox.fund_manager import FundManager

    ok, message = FundManager(USER).block_margin(Decimal(str(amount)), "seed")
    assert ok, message
    release_sessions()


def _wrap(monkeypatch, cls, names, before):
    for name in names:
        real = getattr(cls, name, None)
        if real is None:
            continue

        def wrapper(self, *args, _real=real, **kwargs):
            before()
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(cls, name, wrapper)


def _position(position_id):
    from database.sandbox_db import SandboxPositions, db_session

    db_session.remove()
    row = SandboxPositions.query.filter_by(id=position_id).first()
    state = None if row is None else (row.quantity, row.margin_blocked)
    db_session.remove()
    return state


def test_an_expired_position_settles_once(monkeypatch):
    """Two views of the position book settle the same expired future once."""
    from database.sandbox_db import SandboxPositions
    from sandbox.fund_manager import FundManager
    from sandbox.position_manager import PositionManager

    expired = _seed_position("NIFTY01JAN24FUT", "NFO", "NRML", -50, 100, 90, 100000)
    # A second position keeps enough margin reserved that a double release is
    # not simply refused by the reserved-margin ceiling.
    _seed_position("RELIANCE", "NSE", "CNC", 10, 2500, 2500, 200000)
    _block(300000)

    meet = Rendezvous()
    _wrap(monkeypatch, FundManager, ["release_margin", "stage_release_margin"], meet)

    def view():
        position = SandboxPositions.query.filter_by(id=expired).first()
        PositionManager(USER)._check_and_close_expired_positions([position])

    run_in_threads([view, view])

    assert _position(expired)[0] == 0
    funds = funds_of(USER)
    close_pnl = (Decimal("100") - Decimal("90")) * 50
    assert funds["used"] == Decimal("200000.00")
    assert funds["realized"] == close_pnl
    assert funds["available"] == CAPITAL - 300000 + 100000 + close_pnl


def test_the_minute_sweep_and_a_position_view_settle_once(monkeypatch):
    """The square-off job's sweep and the position book race on one contract."""
    from database.sandbox_db import SandboxPositions
    from sandbox.fund_manager import FundManager
    from sandbox.position_manager import PositionManager, cleanup_expired_contracts

    expired = _seed_position("BANKNIFTY01JAN24FUT", "NFO", "NRML", 30, 200, 210, 60000)
    _seed_position("RELIANCE", "NSE", "CNC", 10, 2500, 2500, 200000)
    _block(260000)

    meet = Rendezvous()
    _wrap(monkeypatch, FundManager, ["release_margin", "stage_release_margin"], meet)

    def view():
        position = SandboxPositions.query.filter_by(id=expired).first()
        PositionManager(USER)._check_and_close_expired_positions([position])

    run_in_threads([cleanup_expired_contracts, view])

    assert _position(expired)[0] == 0
    funds = funds_of(USER)
    close_pnl = (Decimal("210") - Decimal("200")) * 30
    assert funds["used"] == Decimal("200000.00")
    assert funds["realized"] == close_pnl


def test_t1_settlement_runs_once(monkeypatch):
    """Two catch-ups fold yesterday's CNC buy into the holding once."""
    from database.sandbox_db import SandboxHoldings, db_session
    from sandbox.fund_manager import FundManager
    from sandbox.holdings_manager import HoldingsManager

    position = _seed_position("RELIANCE", "NSE", "CNC", 70, 1000, 1010, 70000)
    _block(170000)  # 70,000 for the position, 100,000 for something else

    meet = Rendezvous()
    _wrap(
        monkeypatch,
        FundManager,
        ["transfer_margin_to_holdings", "stage_transfer_margin_to_holdings"],
        meet,
    )

    results = run_in_threads([lambda: HoldingsManager(USER).process_t1_settlement()] * 2)
    assert all(r[0] is True for r in results), results

    assert _position(position) is None
    db_session.remove()
    holding = SandboxHoldings.query.filter_by(user_id=USER, symbol="RELIANCE").one()
    assert holding.quantity == 70
    db_session.remove()
    funds = funds_of(USER)
    assert funds["used"] == Decimal("100000.00")
    assert funds["available"] == CAPITAL - 170000


def test_a_stale_mis_position_is_settled_once(monkeypatch):
    """Two login catch-ups settle yesterday's MIS position once."""
    from database import token_db
    from sandbox.catch_up_processor import catch_up_mis_squareoff

    stale = _seed_position("RELIANCE", "NSE", "MIS", 40, 2500, 2550, 20000, updated_at=LONG_AGO)
    _seed_position("ZEEL", "NSE", "CNC", 100, 200, 200, 50000)
    _block(70000)

    meet = Rendezvous()
    real_info = token_db.get_symbol_info

    def info_after_meeting(symbol, exchange):
        if symbol == "RELIANCE":
            meet()
        return real_info(symbol, exchange)

    monkeypatch.setattr(token_db, "get_symbol_info", info_after_meeting)

    run_in_threads([catch_up_mis_squareoff, catch_up_mis_squareoff])

    assert _position(stale)[0] == 0
    funds = funds_of(USER)
    pnl = (Decimal("2550") - Decimal("2500")) * 40
    assert funds["used"] == Decimal("50000.00")
    assert funds["realized"] == pnl
    assert funds["today"] == 0
    assert funds["available"] == CAPITAL - 70000 + 20000 + pnl


def test_a_second_catch_up_trigger_skips_while_one_runs(monkeypatch):
    """Six logins at once start one catch-up sweep; the guard frees afterwards."""
    from sandbox import catch_up_processor

    started = threading.Event()
    release = threading.Event()
    runs = []

    def slow_sweep():
        runs.append(1)
        started.set()
        release.wait(10)

    monkeypatch.setattr(catch_up_processor, "catch_up_mis_squareoff", slow_sweep)
    for name in (
        "catch_up_t1_settlement",
        "catch_up_daily_pnl_reset",
        "catch_up_daily_pnl_snapshot",
        "catch_up_gtts",
    ):
        monkeypatch.setattr(catch_up_processor, name, lambda: None)

    first = threading.Thread(target=catch_up_processor.run_catch_up_tasks, daemon=True)
    first.start()
    assert started.wait(10)
    run_in_threads([catch_up_processor.run_catch_up_tasks] * 5, timeout=5)
    release.set()
    first.join(10)
    assert len(runs) == 1

    def failing_sweep():
        runs.append(1)
        raise RuntimeError("sweep failed")

    monkeypatch.setattr(catch_up_processor, "catch_up_mis_squareoff", failing_sweep)
    catch_up_processor.run_catch_up_tasks()
    catch_up_processor.run_catch_up_tasks()
    assert len(runs) == 3, "a sweep that raised kept the guard"
