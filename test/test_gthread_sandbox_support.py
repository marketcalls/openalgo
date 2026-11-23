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
from contextlib import contextmanager
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


def set_charges(enabled: bool) -> None:
    """Switch sandbox brokerage and statutory charges on or off in the test database."""
    from database.sandbox_db import db_session, set_configs
    from sandbox.charges import CHARGES_ENABLED_KEY

    assert set_configs({CHARGES_ENABLED_KEY: "true" if enabled else "false"})
    db_session.remove()


def seed_symbols(specs=None) -> None:
    """Make sure the symbol master holds the instruments these tests trade.

    Checked on every call, not once per process. The symbol table is shared by
    the whole suite and other tests clear it (the master contract guard tests
    delete every row), so a sandbox test that ran after one of them found no
    RELIANCE and every order was refused with "Symbol not found": it passed
    alone and failed in a full run.
    """
    from database.symbol import SymToken
    from database.symbol import db_session as symbol_session

    for spec in SYMBOLS if specs is None else specs:
        exists = SymToken.query.filter_by(symbol=spec["symbol"], exchange=spec["exchange"]).first()
        if exists is None:
            symbol_session.add(SymToken(**spec))
    symbol_session.commit()
    symbol_session.remove()


def remove_symbols(specs) -> None:
    """Take a test's own instruments back out of the shared symbol master.

    A test that adds an instrument has to remove it, and should not name it
    after a real underlying. The charge tests once left a NIFTY option with a
    lot of 75 behind, and three strategy tests that read NIFTY's lot size
    afterwards got 75 where they expect 65. Only the row with the test's own
    token is removed, so another test's row of the same name is left alone.
    """
    from database.symbol import SymToken
    from database.symbol import db_session as symbol_session

    for spec in specs:
        SymToken.query.filter_by(
            symbol=spec["symbol"], exchange=spec["exchange"], token=spec["token"]
        ).delete()
    symbol_session.commit()
    symbol_session.remove()


def prepare_databases() -> None:
    """Create the sandbox tables once per process, and put the shared state right.

    Every call also reseeds the symbol master (see :func:`seed_symbols`) and
    switches charges off. These suites pin margin and P&L arithmetic under
    races, to the paisa, and a fill that also pays brokerage would move every
    balance they assert on. With the switch off a fill must leave exactly the
    figures it left before charges existed, which is itself worth holding.
    ``test_gthread_sandbox_charges.py`` switches them on. It is done on every
    call, not once, because the test database is a file that outlives the run
    and a test that resets the sandbox settings puts the switch back to its
    default.
    """
    global _prepared
    if not _prepared:
        from database.sandbox_db import init_db as init_sandbox_db
        from database.symbol import init_db as init_symbol_db

        try:
            init_symbol_db()
        except Exception:
            pass
        init_sandbox_db()
        _prepared = True
    seed_symbols()
    set_charges(False)


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
        "charges": row.total_charges,
        "today_charges": row.today_charges,
    }
    db_session.remove()
    return values


@contextmanager
def only_funds_of(user_id: str):
    """Leave ``user_id`` as the only funds row for the duration of the block.

    A starting-capital change applies to every funds row in the database, and
    the test database is shared with the rest of the suite, so the other rows
    are set aside and put back exactly as they were afterwards.
    """
    from database.sandbox_db import SandboxFunds, db_session

    table = SandboxFunds.__table__
    saved = [
        dict(row._mapping)
        for row in db_session.execute(table.select().where(table.c.user_id != user_id)).all()
    ]
    db_session.execute(table.delete().where(table.c.user_id != user_id))
    db_session.commit()
    db_session.remove()
    try:
        yield
    finally:
        release_sessions()
        for row in saved:
            db_session.execute(table.insert().values(row))
        db_session.commit()
        db_session.remove()


@contextmanager
def configs_restored(keys):
    """Put the given sandbox config values back as they were after the block."""
    from database.sandbox_db import SandboxConfig, db_session

    saved = {
        key: row.config_value
        for key in keys
        if (row := SandboxConfig.query.filter_by(config_key=key).first()) is not None
    }
    db_session.remove()
    try:
        yield
    finally:
        release_sessions()
        for key in keys:
            row = SandboxConfig.query.filter_by(config_key=key).first()
            if key in saved:
                if row is not None:
                    row.config_value = saved[key]
            elif row is not None:
                db_session.delete(row)
        db_session.commit()
        db_session.remove()


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
