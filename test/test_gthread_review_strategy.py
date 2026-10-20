"""Strategy and Flow findings from the gthread review.

strategy-01. The early-update stash held one frame per broker order id. A
broker pushes an order's "open" and its "complete" within milliseconds, and
under the gthread worker two update workers can both miss the row at once.
Either one worker's re-check popped the other's frame and applied its own, or
the older frame overwrote the newer in the slot, and in both cases the fill
was lost: the leg kept no entry price, so no stop and no target.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import order_events, state

USER = "gthread_review_strategy_user"


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            for run in store.list_runs(row["id"]):
                state.clear_run_state(run["id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def unacknowledged_order():
    """A run with one entry row the broker has not acknowledged yet."""
    created, error = store.create_strategy(
        USER,
        {
            "name": "gthread review order events",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "legs": [{"id": 1, "segment": "options", "position": "S", "lots": 1}],
        },
    )
    assert error is None, error
    run = store.create_run(created["id"], "sandbox", "zerodha")
    row = store.record_order(
        run.id,
        leg_id=1,
        kind="entry",
        order={
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "status": "pending",
        },
    )
    assert row is not None
    ids = SimpleNamespace(strategy_id=created["id"], run_id=run.id, order_id=row.id)
    store.db_session.remove()
    return ids


def _frame(orderid, status):
    filled = status == "complete"
    return SimpleNamespace(
        orderid=orderid,
        order_status=status,
        average_price=142.5 if filled else 0,
        filled_quantity=75 if filled else 0,
        rejection_reason="",
    )


def _record(order, broker_order_id):
    try:
        assert store.update_order(order.order_id, status="open", broker_order_id=broker_order_id)
    finally:
        store.db_session.remove()


def _stored(order, broker_order_id):
    store.db_session.remove()
    rows = [o for o in store.list_orders(order.run_id) if o["broker_order_id"] == broker_order_id]
    store.db_session.remove()
    return rows[0]


def _join(*threads):
    for thread in threads:
        thread.join(20)
    assert not any(thread.is_alive() for thread in threads), "a worker never finished"


def test_a_sibling_workers_fill_is_applied_when_a_replay_ran_between(unacknowledged_order):
    """Both workers miss the row, the engine records it and replays nothing,
    then both stash. The first to look again must apply both frames."""
    broker_order_id = "BRK-REVIEW-TWO-1"
    real_lookup = store.get_order_by_broker_id
    real_expire = store.db_session.expire_all
    lookups: dict[str, int] = {}
    both_missed = threading.Barrier(3)
    recorded = threading.Event()
    w2_stashed = threading.Event()
    w1_done = threading.Event()

    def lookup(order_id):
        name = threading.current_thread().name
        if name not in ("W1", "W2"):
            return real_lookup(order_id)
        lookups[name] = lookups.get(name, 0) + 1
        if lookups[name] == 1:
            both_missed.wait(10)
            assert recorded.wait(10), "the recording thread never ran"
            return None
        # The re-check after the stash. W1 looks once W2 has stashed too; W2
        # looks only after W1 is done.
        if name == "W1":
            assert w2_stashed.wait(10), "W2 never stashed"
        else:
            assert w1_done.wait(10), "W1 never finished"
        return real_lookup(order_id)

    def expire_all():
        # Called straight after a worker's stash, when it is about to look again.
        if threading.current_thread().name == "W2":
            w2_stashed.set()
        return real_expire()

    def worker(status, done=None):
        try:
            order_events._apply_update(broker_order_id, _frame(broker_order_id, status))
        finally:
            if done is not None:
                done.set()

    def recorder():
        both_missed.wait(10)
        try:
            _record(unacknowledged_order, broker_order_id)
            order_events.replay_for(broker_order_id)  # nothing is held yet
        finally:
            store.db_session.remove()
            recorded.set()

    with (
        patch.object(store, "get_order_by_broker_id", side_effect=lookup),
        patch.object(store.db_session, "expire_all", side_effect=expire_all),
        patch("services.strategy_module.engine.apply_fill") as apply_fill,
    ):
        w1 = threading.Thread(target=worker, args=("open", w1_done), name="W1")
        w2 = threading.Thread(target=worker, args=("complete",), name="W2")
        rec = threading.Thread(target=recorder, name="REC")
        for thread in (w1, w2, rec):
            thread.start()
        _join(w1, w2, rec)
    try:
        assert apply_fill.call_count == 1, (
            "the complete frame was popped by the other worker and dropped: the leg "
            "keeps no entry price, so no stop and no target"
        )
        args, kwargs = apply_fill.call_args
        assert args[:3] == (unacknowledged_order.run_id, 1, 142.5)
        assert kwargs["order_row_id"] == unacknowledged_order.order_id
        stored = _stored(unacknowledged_order, broker_order_id)
        assert stored["status"] == "complete"
        assert order_events._pending_updates.get(broker_order_id) is None
    finally:
        order_events._pending_updates.pop(broker_order_id, None)


def test_a_fill_held_before_a_later_open_is_still_replayed(unacknowledged_order):
    """No replay in between: the complete frame is held first and the open
    frame after it. One slot kept only the open, and the replay lost the fill."""
    broker_order_id = "BRK-REVIEW-TWO-2"
    real_lookup = store.get_order_by_broker_id

    def lookup(order_id):
        name = threading.current_thread().name
        if name == "W1":
            # The open frame's worker misses the row after the fill is held.
            deadline = time.monotonic() + 10
            while order_events._pending_updates.get(broker_order_id) is None:
                assert time.monotonic() < deadline, "the fill was never held"
                time.sleep(0.005)
            return None
        if name == "W2":
            return None
        return real_lookup(order_id)

    with (
        patch.object(store, "get_order_by_broker_id", side_effect=lookup),
        patch("services.strategy_module.engine.apply_fill") as apply_fill,
    ):
        w1 = threading.Thread(
            target=order_events._apply_update,
            args=(broker_order_id, _frame(broker_order_id, "open")),
            name="W1",
        )
        w2 = threading.Thread(
            target=order_events._apply_update,
            args=(broker_order_id, _frame(broker_order_id, "complete")),
            name="W2",
        )
        w1.start()
        w2.start()
        _join(w1, w2)
        assert apply_fill.call_count == 0, "there is no row to apply it to yet"

        _record(unacknowledged_order, broker_order_id)
        order_events.replay_for(broker_order_id)
    try:
        assert apply_fill.call_count == 1, "the replay applied only the open frame"
        assert _stored(unacknowledged_order, broker_order_id)["status"] == "complete"
    finally:
        order_events._pending_updates.pop(broker_order_id, None)


def test_the_frames_held_for_one_order_are_bounded():
    """An id another surface keeps updating is capped, oldest frames first."""
    broker_order_id = "NOT-OURS-REVIEW-CAP"
    try:
        for n in range(order_events._MAX_FRAMES_PER_ORDER + 5):
            order_events._stash_until_recorded(
                broker_order_id, SimpleNamespace(n=n), order_events._replays
            )
        held = order_events._pending_updates.get(broker_order_id)
        assert len(held) == order_events._MAX_FRAMES_PER_ORDER
        assert held[-1].n == order_events._MAX_FRAMES_PER_ORDER + 4
    finally:
        order_events._pending_updates.pop(broker_order_id, None)
