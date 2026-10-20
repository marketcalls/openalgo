"""Commit-owning fund operations close failed CAS transactions; stages remain caller-owned."""

from decimal import Decimal

import pytest
from test_gthread_sandbox_support import (
    funds_of,
    prepare_databases,
    release_sessions,
    reset_user,
)

USER = "gthread_funds_cas_cleanup"
OTHER = "gthread_funds_cas_staged"


@pytest.fixture(autouse=True)
def fresh_accounts():
    prepare_databases()
    reset_user(USER)
    reset_user(OTHER)
    release_sessions()
    yield
    release_sessions()


def _stale_snapshot(monkeypatch):
    from sandbox import fund_manager

    old = fund_manager.read_funds_snapshot(USER)
    release_sessions()
    ok, message = fund_manager.FundManager(USER).block_margin(Decimal("10"))
    assert ok, message
    release_sessions()
    monkeypatch.setattr(fund_manager, "read_funds_snapshot", lambda _user: old)
    return fund_manager


def _try_external_write():
    import sqlite3

    from database.sandbox_db import engine

    connection = sqlite3.connect(engine.url.database, timeout=0.2, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        connection.close()


def _add_one(funds):
    return True, "add one", {"available_balance": funds["available_balance"] + 1}


def test_failed_cas_does_not_hold_the_sqlite_writer_lock(monkeypatch):
    fund_manager = _stale_snapshot(monkeypatch)

    ok, message = fund_manager.FundManager(USER).block_margin(Decimal("1"))

    assert not ok and message == fund_manager.FUNDS_BUSY_MESSAGE
    assert _try_external_write(), "failed CAS left a SQLite write transaction open"


def test_failed_cas_does_not_rollback_a_callers_staged_margin(monkeypatch):
    from database.sandbox_db import db_session
    from sandbox.fund_manager import FundManager

    fund_manager = _stale_snapshot(monkeypatch)
    ok, message = FundManager(OTHER).stage_margin_delta(Decimal("100"), "caller stage")
    assert ok, message

    ok, message = fund_manager.apply_funds_change(USER, _add_one)
    assert not ok and message == fund_manager.FUNDS_BUSY_MESSAGE
    db_session.commit()

    assert funds_of(OTHER)["used"] == Decimal("100.00")
