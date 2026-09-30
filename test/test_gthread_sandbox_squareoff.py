"""The sandbox auto square-off closes each MIS position once (gthread audit trading-06).

At the square-off minute two scheduler jobs run the same sweep: the
exchange's own job and the one-minute backup, on two scheduler threads
(max_instances is per job, not per function). Each loaded the open MIS
positions and sent a closing order for each, so a position was sold twice and
left short. Within one sweep the closing order was also sized from the
position as the sweep loaded it, so a position the trader reversed in the
meantime was "closed" in the wrong direction and doubled.

Sweeps now run one after another, the close reads the committed quantity under
the position's lock, and every sandbox scheduler job releases its database
sessions when it finishes. That matters for the 23:30 MCX square-off as much
as the 15:15 one: it must happen exactly once.
"""

from __future__ import annotations

import threading
from datetime import time
from decimal import Decimal

import pytest
from test_gthread_sandbox_support import (
    CAPITAL,
    funds_of,
    prepare_databases,
    quote,
    release_sessions,
    reset_user,
    run_in_thread,
    run_in_threads,
)

USER = "gthread_sandbox_squareoff"
PRICE = Decimal("2500.00")
MARGIN = Decimal("25000.00")  # 50 x 2500 at the default MIS leverage of 5


@pytest.fixture(autouse=True)
def fresh_account(monkeypatch):
    prepare_databases()
    reset_user(USER)
    release_sessions()
    from sandbox import position_manager
    from sandbox.execution_engine import ExecutionEngine
    from sandbox.squareoff_manager import SquareOffManager

    monkeypatch.setattr(
        ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(PRICE)
    )
    # The sweep also settles expired contracts and cancels their orders for
    # every account in the database; keep it to this test's own position.
    monkeypatch.setattr(position_manager, "cleanup_expired_contracts", lambda: None)
    monkeypatch.setattr(SquareOffManager, "_cancel_expired_contract_orders", lambda self: 0)
    yield
    release_sessions()


def _seed_mis_long():
    from database.sandbox_db import SandboxPositions, db_session
    from sandbox.fund_manager import FundManager

    db_session.add(
        SandboxPositions(
            user_id=USER,
            symbol="RELIANCE",
            exchange="BSE",
            product="MIS",
            quantity=50,
            average_price=PRICE,
            ltp=PRICE,
            pnl=Decimal("0.00"),
            pnl_percent=Decimal("0.00"),
            accumulated_realized_pnl=Decimal("0.00"),
            today_realized_pnl=Decimal("0.00"),
            margin_blocked=MARGIN,
        )
    )
    db_session.commit()
    assert FundManager(USER).block_margin(MARGIN, "seed")[0]
    release_sessions()


def _due_manager():
    """A square-off manager for which only BSE is past its square-off time."""
    from sandbox.squareoff_manager import SquareOffManager

    manager = SquareOffManager()
    manager.square_off_times = {exchange: time(23, 59, 59) for exchange in manager.square_off_times}
    manager.square_off_times["BSE"] = time(0, 0)
    return manager


def _state():
    from database.sandbox_db import SandboxPositions, SandboxTrades, db_session

    db_session.remove()
    position = SandboxPositions.query.filter_by(user_id=USER, symbol="RELIANCE").first()
    trades = SandboxTrades.query.filter_by(user_id=USER, symbol="RELIANCE").all()
    state = {
        "quantity": position.quantity,
        "trades": [(t.action, t.quantity) for t in trades],
    }
    db_session.remove()
    return state


def test_the_primary_and_backup_sweeps_close_a_position_once(monkeypatch):
    from sandbox.order_manager import OrderManager

    _seed_mis_long()
    barrier = threading.Barrier(2)
    real_place = OrderManager.place_order

    def place_after_both_sweeps_decided(self, *args, **kwargs):
        try:
            barrier.wait(2)
        except threading.BrokenBarrierError:
            # The other sweep is waiting for this one to finish: the fix.
            pass
        return real_place(self, *args, **kwargs)

    monkeypatch.setattr(OrderManager, "place_order", place_after_both_sweeps_decided)

    manager = _due_manager()
    run_in_threads([manager.check_and_square_off, manager.check_and_square_off])

    state = _state()
    assert state["quantity"] == 0
    assert state["trades"] == [("SELL", 50)]
    funds = funds_of(USER)
    assert funds["used"] == 0
    assert funds["available"] == CAPITAL


def test_a_position_reversed_during_the_sweep_is_closed_as_it_now_stands(monkeypatch):
    """The closing order follows the committed quantity, not the sweep's copy."""
    from sqlalchemy import update

    from database.sandbox_db import SandboxPositions, db_session
    from sandbox.position_manager import PositionManager

    _seed_mis_long()
    real_close = PositionManager.close_position
    flipped = []

    def reverse_then_close(self, symbol, exchange, product):
        if not flipped:
            flipped.append(1)

            def reverse():
                db_session.execute(
                    update(SandboxPositions)
                    .where(SandboxPositions.user_id == USER, SandboxPositions.symbol == symbol)
                    .values(quantity=-50)
                )
                db_session.commit()

            run_in_thread(reverse)
        return real_close(self, symbol, exchange, product)

    monkeypatch.setattr(PositionManager, "close_position", reverse_then_close)

    run_in_thread(_due_manager().check_and_square_off)

    assert flipped
    state = _state()
    assert state["quantity"] == 0
    assert state["trades"] == [("BUY", 50)]


def test_every_scheduler_job_releases_its_sessions(monkeypatch):
    """A scheduler thread must not keep its connection and rows between runs."""
    from database.sandbox_db import SandboxConfig, db_session
    from sandbox import squareoff_thread
    from sandbox.squareoff_manager import SquareOffManager

    class RecordingScheduler:
        def __init__(self):
            self.jobs = {}

        def add_job(self, func, id, **kwargs):
            self.jobs[id] = func
            return type("Job", (), {"id": id})()

    def touches_the_database(*args, **kwargs):
        SandboxConfig.query.first()

    monkeypatch.setattr(SquareOffManager, "check_and_square_off", touches_the_database)
    from sandbox import fund_manager, holdings_manager

    monkeypatch.setattr(holdings_manager, "process_all_t1_settlements", touches_the_database)
    monkeypatch.setattr(fund_manager, "reset_all_user_funds", touches_the_database)
    monkeypatch.setattr(
        squareoff_thread,
        "get_config",
        lambda key, default=None: {
            "reset_day": "Sunday",
        }.get(key, default),
    )

    scheduler = RecordingScheduler()
    squareoff_thread._schedule_square_off_jobs(scheduler)
    assert {"squareoff_backup", "t1_settlement", "auto_reset", "daily_pnl_snapshot"} <= set(
        scheduler.jobs
    )

    def job_leaves_no_session(job):
        def run():
            SandboxConfig.query.first()  # the thread has a session before the job
            try:
                job()
            except Exception:
                pass
            return db_session.registry.has()

        return run

    # The two P&L jobs write every account in the shared test database, so they
    # are not run here; they carry the same wrapper, checked below.
    runnable = {
        job_id: job
        for job_id, job in scheduler.jobs.items()
        if job_id not in ("daily_pnl_snapshot", "daily_pnl_reset")
    }
    leftovers = {
        job_id: run_in_thread(job_leaves_no_session(job)) for job_id, job in runnable.items()
    }
    assert not any(leftovers.values()), leftovers
    assert all(hasattr(job, "__wrapped__") for job in scheduler.jobs.values())
