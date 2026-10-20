"""A prune that matches nothing must not hold SQLite's write lock.

`_prune_old_tags` and `_prune_pending_fills` run from application startup. A
DELETE takes SQLite's write transaction the moment it executes, whether or not
it matches a row, and both used to commit only when the row count was truthy.
A prune that matched nothing, which is the ordinary case, therefore left the
transaction open on the startup thread's session. Startup runs inside one app
context spanning the whole of `_init_databases_and_schedulers`, so
`teardown_appcontext` does not fire until every step has finished and nothing
released it in between: the write lock was held straight through the steps that
still had writing to do, and every other writer on openalgo.db backed off for
its full budget and failed with "database is locked". Strategy recovery was one
of them, which is how a finished run stayed open across every restart.

The first test asserts the defect itself, so this file cannot pass vacuously.
"""

from datetime import datetime, timedelta

import pytest

from database import strategy_book_db as book


@pytest.fixture(autouse=True)
def clean_book():
    """Own the schema outright.

    The test database is shared with every other suite, and this file is the
    only one that touches the strategy book, so it creates its tables rather
    than assuming whichever suite ran first left them there.
    """
    book.Base.metadata.create_all(bind=book.engine)
    book.db_session.remove()
    yield
    book.db_session.remove()


def _write_lock_is_free() -> bool:
    """Whether a second connection can take the write lock right now.

    A second engine on the same URL rather than a raw sqlite3 connect: the URL
    is relative, and connecting to a mis-resolved relative path would silently
    create an empty database rather than fail, which reads as a passing test
    against a file nothing else uses. A short busy timeout keeps the check
    quick; the application itself waits fifteen seconds and then fails.
    """
    import sqlalchemy
    from sqlalchemy.pool import NullPool

    from database.strategy_book_db import engine as book_engine

    probe = sqlalchemy.create_engine(
        book_engine.url, poolclass=NullPool, connect_args={"timeout": 0.5}
    )
    try:
        with probe.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            conn.exec_driver_sql("ROLLBACK")
        return True
    except sqlalchemy.exc.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return False
        raise
    finally:
        probe.dispose()


def test_a_prune_that_matches_nothing_releases_the_write_lock():
    """The defect: committing only on a non-zero row count."""
    assert _write_lock_is_free(), "another writer already holds the lock"

    # Nothing is old enough to prune, so the DELETE matches zero rows.
    book._prune_old_tags()

    assert _write_lock_is_free(), (
        "the write lock is still held after a prune that deleted nothing. "
        "The DELETE opened a write transaction that was never committed."
    )


def test_the_pending_fill_prune_releases_it_too():
    assert _write_lock_is_free(), "another writer already holds the lock"

    book._prune_pending_fills()
    book.db_session.remove()

    assert _write_lock_is_free(), "the pending-fill prune left its transaction open"


def test_a_prune_that_does_delete_still_commits(tmp_path, monkeypatch):
    """The rows really go, so the fix did not turn the prune into a no-op.

    On its own database. The shared test database is created and reset by
    whichever suites run first, and this assertion needs a table it can rely
    on being there; the lock assertions above deliberately use the shared one,
    because that is where the contention they describe actually happens.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.pool import NullPool

    own = create_engine(f"sqlite:///{tmp_path / 'book.db'}", poolclass=NullPool)
    session = scoped_session(sessionmaker(bind=own))
    book.Base.metadata.create_all(bind=own)
    monkeypatch.setattr(book, "db_session", session)

    old = datetime.now() - book._TAG_RETENTION - timedelta(days=1)
    session.add(
        book.StrategyOrderTag(
            orderid="prune-test-1",
            user_id="prune-test-user",
            strategy="prune-test",
            symbol="RELIANCE",
            exchange="NSE",
            product="CNC",
            created_at=old,
        )
    )
    session.commit()
    session.remove()

    book._prune_old_tags()

    remaining = session.query(book.StrategyOrderTag).filter_by(orderid="prune-test-1").count()
    session.remove()
    own.dispose()
    assert remaining == 0, "the prune no longer deletes what it is supposed to"


def test_startup_initialisation_leaves_no_open_transaction():
    """init_strategy_book_db is what actually runs at boot."""
    assert _write_lock_is_free(), "another writer already holds the lock"

    book.init_strategy_book_db()

    assert _write_lock_is_free(), (
        "init_strategy_book_db left the write lock held, which is what blocked "
        "strategy recovery at startup"
    )
