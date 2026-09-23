"""Shared set-up for the ``test_gthread_sandbox_*`` race tests. It holds no tests.

The sandbox keeps a scoped SQLAlchemy session per thread. Most of the races
these files reproduce come from exactly that: a thread whose session loaded a
row earlier and is handed that same stale object again, or two threads each
acting on their own snapshot of one row. So every race here runs on real
threads with their own sessions, against the isolated sandbox test database
that ``test/conftest.py`` points the process at, and every helper thread
releases its sessions when it finishes.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

#: Instruments these tests trade. Cash equity, lot size 1, so margin is
#: quantity x price / leverage with the default CNC leverage of 1.
SYMBOLS = [
    {
        "symbol": "RELIANCE",
        "brsymbol": "RELIANCE-EQ",
        "name": "RELIANCE INDUSTRIES",
        "exchange": "NSE",
        "brexchange": "NSE",
        "token": "2885",
        "lotsize": 1,
        "instrumenttype": "EQ",
        "tick_size": 0.05,
        "contract_value": 1.0,
    },
    {
        "symbol": "ZEEL",
        "brsymbol": "ZEEL-EQ",
        "name": "ZEE ENTERTAINMENT",
        "exchange": "NSE",
        "brexchange": "NSE",
        "token": "3812",
        "lotsize": 1,
        "instrumenttype": "EQ",
        "tick_size": 0.05,
        "contract_value": 1.0,
    },
    {
        # BSE, so the square-off tests can make only their own exchange due
        # and leave any other test's MIS positions in the shared database alone.
        "symbol": "RELIANCE",
        "brsymbol": "RELIANCE",
        "name": "RELIANCE INDUSTRIES",
        "exchange": "BSE",
        "brexchange": "BSE",
        "token": "500325",
        "lotsize": 1,
        "instrumenttype": "EQ",
        "tick_size": 0.05,
        "contract_value": 1.0,
    },
]

CAPITAL = Decimal("10000000.00")

_prepared = False


def prepare_databases() -> None:
    """Create the sandbox tables and seed the symbol master, once per process."""
    global _prepared
    if _prepared:
        return
    from database.sandbox_db import init_db as init_sandbox_db
    from database.symbol import SymToken
    from database.symbol import db_session as symbol_session
    from database.symbol import init_db as init_symbol_db

    try:
        init_symbol_db()
    except Exception:
        pass
    init_sandbox_db()
    for spec in SYMBOLS:
        exists = SymToken.query.filter_by(symbol=spec["symbol"], exchange=spec["exchange"]).first()
        if exists is None:
            symbol_session.add(SymToken(**spec))
    symbol_session.commit()
    symbol_session.remove()
    _prepared = True


def reset_user(user_id: str, capital: Decimal = CAPITAL) -> None:
    """Delete every sandbox row of ``user_id`` and give it fresh funds."""
    from datetime import datetime

    from database.sandbox_db import (
        SandboxFunds,
        SandboxGTT,
        SandboxHoldings,
        SandboxOrders,
        SandboxPositions,
        SandboxTrades,
        db_session,
    )

    for model in (SandboxOrders, SandboxTrades, SandboxPositions, SandboxHoldings, SandboxGTT):
        model.query.filter_by(user_id=user_id).delete()
    SandboxFunds.query.filter_by(user_id=user_id).delete()
    db_session.add(
        SandboxFunds(
            user_id=user_id,
            total_capital=capital,
            available_balance=capital,
            used_margin=Decimal("0.00"),
            realized_pnl=Decimal("0.00"),
            today_realized_pnl=Decimal("0.00"),
            unrealized_pnl=Decimal("0.00"),
            total_pnl=Decimal("0.00"),
            last_reset_date=datetime.now(),
            reset_count=0,
        )
    )
    db_session.commit()
    db_session.remove()


def funds_of(user_id: str) -> dict:
    """The user's funds row as the database holds it now."""
    from database.sandbox_db import SandboxFunds, db_session

    db_session.remove()
    row = SandboxFunds.query.filter_by(user_id=user_id).first()
    values = {
        "available": row.available_balance,
        "used": row.used_margin,
        "realized": row.realized_pnl,
        "today": row.today_realized_pnl,
        "total_capital": row.total_capital,
        "total_pnl": row.total_pnl,
    }
    db_session.remove()
    return values


def release_sessions() -> None:
    """Release every scoped session bound to the calling thread."""
    from utils.db_sessions import remove_all_scoped_sessions

    remove_all_scoped_sessions()


def run_in_threads(targets: list[Callable[[], object]], timeout: float = 60.0) -> list:
    """Run each target on its own thread and return their results in order.

    Each thread releases its sessions when it finishes. An exception inside a
    target is returned in its slot rather than lost, and a thread that is
    still running at the timeout fails the test.
    """
    results: list = [None] * len(targets)

    def wrap(index, target):
        try:
            results[index] = target()
        except BaseException as exc:  # returned to the test, not swallowed
            results[index] = exc
        finally:
            release_sessions()

    threads = [
        threading.Thread(target=wrap, args=(i, t), daemon=True) for i, t in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
        assert not thread.is_alive(), "a worker thread did not finish; the code under test hung"
    return results


def run_in_thread(target: Callable[[], object], timeout: float = 60.0):
    """Run one target on a fresh thread (so with a fresh session) and return its result."""
    (result,) = run_in_threads([target], timeout)
    if isinstance(result, BaseException):
        raise result
    return result


def quote(ltp, spread: float = 0.0) -> dict:
    """A quote the engine accepts: LTP inside its own day range."""
    ltp = float(ltp)
    return {
        "ltp": ltp,
        "bid": ltp - spread,
        "ask": ltp + spread,
        "high": ltp * 1.1,
        "low": ltp * 0.9,
    }
