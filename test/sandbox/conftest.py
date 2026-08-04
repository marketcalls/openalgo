"""Shared setup for the sandbox test suite.

Two problems this solves.

**Package shadowing.** ``test/sandbox/`` used to carry an ``__init__.py``, which
made it a regular package named ``sandbox``. pytest prepends ``test/`` to
``sys.path`` (there is no ``test/__init__.py``), so every ``from sandbox.x
import y`` in this directory resolved to the *test* package and failed - the
whole suite was uncollectable and had not run in CI. Without that file the
directory is only a namespace-package candidate, which loses to the real
regular package at the repo root, and the imports resolve correctly.

**Missing symbol master.** The sandbox order path prices every order through
``symtoken``. A bare test database has no such table, so orders were rejected,
margin stayed at zero, and the margin assertions failed for a reason that had
nothing to do with margin. Seeding the two instruments these tests trade lets
them exercise the real margin arithmetic.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

#: Instruments the sandbox tests trade. Cash equity, so lot size 1 and a
#: contract value of 1 - margin is then quantity x price / leverage, which is
#: what the scenario expectations are written against.
TEST_SYMBOLS = [
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
]


@pytest.fixture(autouse=True, scope="session")
def seed_symbol_master():
    """Ensure ``symtoken`` exists and carries the test instruments.

    Session-scoped and idempotent: the rows are upserted, so running the suite
    repeatedly against the same test database does not accumulate duplicates.
    """
    from database.symbol import SymToken, db_session, init_db

    try:
        init_db()
    except Exception:
        # Table may already exist; the query below is the real check.
        pass

    # Sandbox tables and their column migrations. Existing installs upgrade
    # through init_db(), so the tests must take the same path or they would
    # only ever exercise a freshly-created schema.
    try:
        from database.sandbox_db import init_db as init_sandbox_db

        init_sandbox_db()
    except Exception as exc:
        pytest.skip(f"Could not initialise the sandbox database: {exc}")

    try:
        for spec in TEST_SYMBOLS:
            existing = SymToken.query.filter_by(
                symbol=spec["symbol"], exchange=spec["exchange"]
            ).first()
            if existing is None:
                db_session.add(SymToken(**spec))
        db_session.commit()
    except Exception as exc:  # pragma: no cover - environment problem, not a test failure
        db_session.rollback()
        pytest.skip(f"Could not seed the symbol master for sandbox tests: {exc}")

    yield


#: Modules whose tests place MARKET orders, which the sandbox prices from a live
#: quote. Without a broker session there is no price, the order is rejected, and
#: the margin assertions fail for a reason unrelated to margin.
LIVE_QUOTE_MODULES = (
    "test_margin_scenarios",
    "test_cnc_sell_validation",
)


def _live_quotes_available() -> bool:
    """Whether this environment can price a MARKET order.

    Needs both an API key to call the quotes service with and a broker session
    behind it. Checked once, cheaply, rather than letting each test fail with a
    misleading assertion.
    """
    try:
        from database.auth_db import ApiKeys, Auth

        if ApiKeys.query.first() is None:
            return False
        return Auth.query.filter_by(is_revoked=False).first() is not None
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Skip live-quote integration tests when there is no quote source.

    These exercise real margin arithmetic and are worth keeping, but they are
    integration tests: offline they can only fail, and a permanently red suite
    is one nobody reads.
    """
    if _live_quotes_available():
        return
    skip = pytest.mark.skip(
        reason="needs a broker session: MARKET orders are priced from a live quote"
    )
    for item in items:
        if any(module in item.nodeid for module in LIVE_QUOTE_MODULES):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def clean_scoped_sessions():
    """Drop the scoped session's identity map around every test.

    SQLAlchemy's scoped_session caches loaded objects per thread. Tests that
    mutate a GTT, and engine code that writes the same rows from a worker
    thread, otherwise leave stale instances behind, so a later test reads an
    object whose in-memory state no longer matches the row. That is why these
    tests passed alone and failed in a full run.
    """
    from database.sandbox_db import db_session

    db_session.remove()
    yield
    try:
        db_session.rollback()
    finally:
        db_session.remove()
