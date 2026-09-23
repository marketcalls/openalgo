"""Sandbox funds survive two writers at once (gthread audit trading-03, rest-03).

Every balance change used to read the funds row, adjust the loaded object and
commit it. The class lock around block and release serialised those two
against each other, but not against the writers outside it: a GTT's staged
reservation, margin reconciliation after every fill, the starting-capital
change in the settings view. Any of those committing between another
writer's read and its write was erased by that write, which set the balance
from what it had read. And a caller that holds a funds row (reconciling every
account holds all of them) was handed its own earlier copy back by the
session, so it wrote from a balance it read minutes before.

Each change is now a compare-and-set against a fresh read. The tests below
reproduce each lost update on the old code; the last two pin the behaviour
that must not change.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal

import pytest
from test_gthread_sandbox_support import (
    CAPITAL,
    funds_of,
    only_funds_of,
    prepare_databases,
    release_sessions,
    reset_user,
    run_in_thread,
    run_in_threads,
)

USER = "gthread_sandbox_funds"
OTHER = "gthread_sandbox_funds_b"


@pytest.fixture(autouse=True)
def fresh_account():
    prepare_databases()
    reset_user(USER)
    reset_user(OTHER)
    release_sessions()
    yield
    release_sessions()


def test_a_block_waiting_behind_a_staged_gtt_reservation_keeps_it():
    """An order's margin block must not erase a GTT reservation committed first.

    A GTT stages its reservation and commits it with its own row. An order
    blocking margin at that moment read the balance before the reservation
    and, once the GTT committed, wrote that older balance minus its own
    margin: the reservation vanished from the funds while the GTT still held
    it.
    """
    from database.sandbox_db import db_session
    from sandbox.fund_manager import FundManager

    reservation = Decimal("300000.00")
    margin = Decimal("100000.00")
    staged = threading.Event()

    def gtt():
        ok, message = FundManager(USER).stage_margin_delta(reservation, "GTT reserve")
        assert ok, message
        staged.set()
        # Hold the write transaction open while the order reads and then waits.
        time.sleep(0.6)
        db_session.commit()
        return ok

    def order():
        assert staged.wait(10)
        return FundManager(USER).block_margin(margin, "order")

    results = run_in_threads([gtt, order])
    assert results[0] is True
    assert results[1][0] is True, results[1]

    funds = funds_of(USER)
    assert funds["used"] == reservation + margin
    assert funds["available"] == CAPITAL - reservation - margin


def test_reconcile_does_not_erase_a_concurrent_credit(monkeypatch):
    """Reconciliation must not write back a balance read before a credit landed.

    It reads funds, logs the discrepancy, then writes. A credit committed in
    that gap was erased by the old write, which set available_balance from the
    earlier read.
    """
    from sandbox import fund_manager
    from sandbox.fund_manager import FundManager, reconcile_margin

    stuck = Decimal("10000.00")
    run_in_thread(lambda: FundManager(USER).block_margin(stuck, "stuck"))
    credit = Decimal("5000.00")

    real_logger = fund_manager.logger
    fired = []

    class PausingLogger:
        def __getattr__(self, name):
            return getattr(real_logger, name)

        def warning(self, message, *args, **kwargs):
            real_logger.warning(message, *args, **kwargs)
            if "Margin discrepancy detected" in str(message) and not fired:
                fired.append(1)
                run_in_thread(lambda: FundManager(USER).credit_sale_proceeds(credit, "race"))

    monkeypatch.setattr(fund_manager, "logger", PausingLogger())

    has_discrepancy, amount, _ = reconcile_margin(USER, auto_fix=True)
    release_sessions()

    assert fired, "the discrepancy was never reached, so nothing was raced"
    assert has_discrepancy and amount == stuck
    funds = funds_of(USER)
    assert funds["used"] == 0
    assert funds["available"] == CAPITAL + credit


def test_reconcile_decides_on_the_balance_now_not_a_copy_the_caller_holds():
    """A thread holding a funds row must not have reconciliation write from it.

    The all-accounts sweep loads every funds row and keeps them while it
    reconciles each account. The session hands reconciliation that held
    object back unchanged, however stale, so a credit committed by another
    thread since the load was overwritten.
    """
    from database.sandbox_db import SandboxFunds
    from sandbox.fund_manager import FundManager, reconcile_margin

    stuck = Decimal("10000.00")
    run_in_thread(lambda: FundManager(USER).block_margin(stuck, "stuck"))
    credit = Decimal("7000.00")

    held = SandboxFunds.query.filter_by(user_id=USER).first()
    run_in_thread(lambda: FundManager(USER).credit_sale_proceeds(credit, "race"))

    has_discrepancy, amount, _ = reconcile_margin(USER, auto_fix=True)
    assert held is not None
    del held
    release_sessions()

    assert has_discrepancy and amount == stuck
    funds = funds_of(USER)
    assert funds["used"] == 0
    assert funds["available"] == CAPITAL + credit


@pytest.fixture
def only_this_account():
    """Leave USER as the only funds row while a test rebases every account."""
    with only_funds_of(USER):
        yield


def test_rebasing_the_capital_keeps_a_block_committed_while_it_runs(monkeypatch, only_this_account):
    """A starting-capital change must not recompute from a pre-block balance.

    The settings view read every funds row, then wrote each balance as the
    new capital minus the margin it had read. A block committed in between
    was dropped from available_balance while used_margin still held it.
    """
    from sandbox import fund_manager
    from sandbox.fund_manager import FundManager

    rebase = getattr(fund_manager, "rebase_starting_capital", None)
    assert rebase is not None, "capital changes still recompute balances in the view"

    margin = Decimal("250000.00")
    real_read = fund_manager.read_funds_snapshot
    fired = []

    def read_then_block(user_id):
        snapshot = real_read(user_id)
        if user_id == USER and not fired:
            fired.append(1)
            run_in_thread(lambda: FundManager(USER).block_margin(margin, "race"))
        return snapshot

    monkeypatch.setattr(fund_manager, "read_funds_snapshot", read_then_block)

    new_capital = Decimal("20000000.00")
    assert rebase(new_capital) == 1
    release_sessions()

    assert fired
    funds = funds_of(USER)
    assert funds["total_capital"] == new_capital
    assert funds["used"] == margin
    assert funds["available"] == new_capital - margin


def test_two_blocks_at_once_both_land_or_one_is_refused():
    """Sanity: simultaneous blocks either both fit or the second is refused."""
    from sandbox.fund_manager import FundManager

    reset_user(USER, capital=Decimal("1000.00"))
    barrier = threading.Barrier(2)

    def place():
        fm = FundManager(USER)
        barrier.wait(10)
        return fm.block_margin(Decimal("600.00"), "race")

    results = run_in_threads([place, place])
    assert sorted(r[0] for r in results) == [False, True], results

    funds = funds_of(USER)
    assert funds["used"] == Decimal("600.00")
    assert funds["available"] == Decimal("400.00")


def test_the_quiet_path_writes_the_same_figures_as_before():
    """One operation at a time gives exactly the arithmetic the ORM path gave.

    The old code read each balance rounded to two places and wrote the exact
    Decimal result, so a margin with a long fraction rounds differently than
    arithmetic done in the database would. The compare-and-set path computes
    in Python from the same two-place read, and must land on the same figures.
    """
    from database.sandbox_db import SandboxFunds, db_session
    from sandbox.fund_manager import FundManager

    fm = FundManager(USER)
    odd = Decimal("1234.566666666666666666666667")
    pnl = Decimal("10.005")
    assert fm.block_margin(odd)[0]
    assert fm.block_margin(odd)[0]
    assert fm.release_margin(odd, pnl)[0]
    release_sessions()

    def two_places(value):
        return Decimal(f"{float(value):.2f}")

    # Replay of the old arithmetic: each step starts from the two-place read.
    avail = two_places(CAPITAL - odd)
    used = two_places(Decimal("0.00") + odd)
    avail, used = two_places(avail - odd), two_places(used + odd)
    avail, used = two_places(avail + odd + pnl), two_places(used - odd)

    row = SandboxFunds.query.filter_by(user_id=USER).first()
    assert row.available_balance == avail
    assert row.used_margin == used
    assert row.realized_pnl == two_places(pnl)
    assert row.today_realized_pnl == two_places(pnl)
    db_session.remove()
