"""Every sandbox order gets an order id nobody else has (gthread audit trading-02).

The id is the IST date and eight digits. Those eight digits used to be the
clock's microsecond field and a random number from 0 to 99, so the hour, the
minute and the second never reached the id: every order placed on a day drew
from the same hundred million values, and two orders in the same microsecond
from one hundred. A clash fails the insert after the order's margin is already
committed as blocked, leaving the funds held with no order behind them.

It surfaced as a flake in ``test_gthread_sandbox_fills.py``, whose fixed clock
reads 14:00:00.000000: with the microsecond always 0, any two orders in a test
clashed one time in a hundred. The eight digits are now the millisecond of the
IST day, issued strictly increasing within the process, and an id already
stored is skipped.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime as RealDatetime

import pytz
from test_gthread_sandbox_support import (
    prepare_databases,
    release_sessions,
    reset_user,
    run_in_thread,
    run_in_threads,
)

USER = "gthread_sandbox_order_ids"
FROZEN = RealDatetime(2026, 10, 12, 14, 0)
# 14:00:00.000 is 50,400,000 milliseconds into the IST day.
FIRST_ID = "26101250400000"


def _freeze_clock(monkeypatch):
    from sandbox import order_manager

    class FrozenDatetime(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            return tz.localize(FROZEN) if tz else FROZEN

    monkeypatch.setattr(order_manager, "datetime", FrozenDatetime)


def _forget_issued_ids(monkeypatch):
    """Start from a process that has issued no id yet, as after a restart."""
    from sandbox import order_manager

    monkeypatch.setattr(order_manager, "_last_order_day", None, raising=False)
    monkeypatch.setattr(order_manager, "_last_order_seq", -1, raising=False)


def _generate():
    from sandbox.order_manager import OrderManager

    return OrderManager(USER)._generate_order_id()


def _store_order(orderid):
    from database.sandbox_db import SandboxOrders, db_session

    db_session.add(
        SandboxOrders(
            orderid=orderid,
            user_id=USER,
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price_type="MARKET",
            product="CNC",
            order_status="complete",
            pending_quantity=0,
        )
    )
    db_session.commit()


def setup_function():
    prepare_databases()
    reset_user(USER)
    release_sessions()


def teardown_function():
    reset_user(USER)
    release_sessions()


def test_ids_stay_unique_when_the_clock_does_not_move(monkeypatch):
    """More orders than the old scheme had values for, released together.

    With the microsecond frozen the old generator had one hundred possible ids,
    so 160 of them must repeat: this fails on the old code every time.
    """
    _freeze_clock(monkeypatch)
    _forget_issued_ids(monkeypatch)
    threads, per_thread = 8, 20
    barrier = threading.Barrier(threads)

    def worker():
        barrier.wait()
        return [_generate() for _ in range(per_thread)]

    results = run_in_threads([worker] * threads)
    for result in results:
        assert not isinstance(result, BaseException), result
    ids = [orderid for result in results for orderid in result]
    assert len(ids) == threads * per_thread
    assert len(set(ids)) == len(ids), "two orders were given the same order id"


def test_an_id_already_stored_is_skipped(monkeypatch):
    """After a restart the process has forgotten what it issued; the table has not."""
    _freeze_clock(monkeypatch)
    _forget_issued_ids(monkeypatch)
    run_in_thread(lambda: _store_order(FIRST_ID))

    assert run_in_thread(_generate) == "26101250400001"


def test_ids_keep_their_format(monkeypatch):
    """Fourteen digits: the IST date as YYMMDD, then eight digits."""
    ist = pytz.timezone("Asia/Kolkata")
    before = RealDatetime.now(ist).strftime("%y%m%d")
    orderid = run_in_thread(_generate)
    after = RealDatetime.now(ist).strftime("%y%m%d")

    assert re.fullmatch(r"\d{14}", orderid), orderid
    assert orderid[:6] in (before, after)
