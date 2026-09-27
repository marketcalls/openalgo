"""One execution cycle must not get slower as resting orders pile up (issue #1768).

``check_and_execute_pending_orders`` used to sleep ``batch_delay`` (1s) after
every ``order_rate_limit`` (10) pending orders, so a cycle cost roughly
``ceil(N/10) - 1`` seconds no matter what it actually did. Measured before the
fix: 9.1s at 100 resting orders and 14.1s at 150, and a single order's
time-to-fill went from 4.6s with no backlog to 34.8s behind 150 - a 7.6x
regression driven purely by queue depth.

The sleep protected nothing. Quotes for the whole cycle are fetched up front in
one ``_fetch_quotes_batch`` call; inside the loop each order is a dict lookup,
local DB writes and an async EventBus publish. No broker call happens there, and
``ORDER_RATE_LIMIT`` is an inbound-API limit that was being reused to throttle
local work.

The backlog here is deliberately unfillable (no quotes), which is the shape that
actually accumulates: orders that cannot be priced rest forever and inflate every
later cycle. The old code paid full price for doing nothing at all.
"""

import time
import uuid
from datetime import datetime

import pytest
import pytz

from database.sandbox_db import SandboxOrders, db_session
from sandbox.execution_engine import ExecutionEngine

IST = pytz.timezone("Asia/Kolkata")
STRATEGY = "backlog-regression"

#: Generous enough to absorb a slow CI box, far below the old cost at this depth
#: (149 orders x 1s per 10 = 14s before the fix).
BACKLOG_SIZE = 150
MAX_CYCLE_SECONDS = 3.0


@pytest.fixture
def backlog():
    """Seed unfillable resting orders, and clean them up afterwards."""

    def _seed(count):
        SandboxOrders.query.filter_by(strategy=STRATEGY).delete()
        db_session.commit()
        now = datetime.now(IST)
        for _ in range(count):
            db_session.add(
                SandboxOrders(
                    orderid=uuid.uuid4().hex[:14],
                    user_id="backlog-user",
                    symbol="RELIANCE",
                    exchange="NSE",
                    action="BUY",
                    quantity=1,
                    price=1,
                    trigger_price=0,
                    price_type="LIMIT",
                    product="MIS",
                    order_status="open",
                    average_price=0,
                    filled_quantity=0,
                    pending_quantity=1,
                    strategy=STRATEGY,
                    order_timestamp=now,
                    update_timestamp=now,
                )
            )
        db_session.commit()

    yield _seed

    SandboxOrders.query.filter_by(strategy=STRATEGY).delete()
    db_session.commit()


@pytest.fixture
def offline_engine(monkeypatch):
    """An engine with no quote source, so the cycle does no fills at all."""
    monkeypatch.setattr(ExecutionEngine, "_fetch_quote", lambda self, s, e: None)
    monkeypatch.setattr(ExecutionEngine, "_fetch_quotes_batch", lambda self, syms: {})
    # GTT upkeep is a separate concern and hits its own tables; keep this
    # measurement to the order loop.
    monkeypatch.setattr(ExecutionEngine, "_check_pending_gtts", lambda self: None)
    return ExecutionEngine()


def _cycle_seconds(engine):
    start = time.perf_counter()
    engine.check_and_execute_pending_orders()
    return time.perf_counter() - start


def test_cycle_does_not_stall_on_a_large_backlog(backlog, offline_engine):
    """150 resting orders must not add ~14s of sleep to a cycle."""
    backlog(BACKLOG_SIZE)

    elapsed = _cycle_seconds(offline_engine)

    assert elapsed < MAX_CYCLE_SECONDS, (
        f"one cycle took {elapsed:.1f}s with {BACKLOG_SIZE} resting orders; "
        f"the per-batch sleep is back (expected well under {MAX_CYCLE_SECONDS}s)"
    )


def test_cycle_cost_is_flat_in_queue_depth(backlog, offline_engine):
    """Cycle time must not scale with how many orders are resting.

    The old code was linear in queue depth, which is what made the symptom
    compound: a slower cycle stranded more orders, which slowed the next cycle.
    """
    backlog(10)
    small = _cycle_seconds(offline_engine)

    backlog(BACKLOG_SIZE)
    large = _cycle_seconds(offline_engine)

    # The old implementation put ~14s between these two. Allow real per-order
    # work to grow, just not by seconds.
    assert large - small < MAX_CYCLE_SECONDS, (
        f"cycle grew from {small:.2f}s at 10 orders to {large:.2f}s at "
        f"{BACKLOG_SIZE}; cost is scaling with queue depth again"
    )
