"""The strategy book books each fill once, whichever bus worker delivers it.

The event bus runs subscribers on long-lived pool threads, and each thread has
its own scoped session. SQLAlchemy does not refresh an object already in a
session's identity map when it is queried again, so a worker that had loaded
an order's tag earlier kept its old applied-quantity watermark. A duplicate
fill arriving on that worker then read the stale watermark, inside the fill
lock, and booked the same quantity again: 150 on the book for a 100-lot
order, which the exit triggers act on.

The book's subscribers also move to the bus's critical lane, so a burst of
best-effort work (alert sends) can no longer shed a fill or a tag.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

import database.strategy_book_db as book
import subscribers.strategy_book_subscriber as book_subscriber


@pytest.fixture
def own_book(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'book.db').as_posix()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    book.Base.metadata.create_all(bind=engine)
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(book, "db_session", session)
    yield session
    session.remove()
    engine.dispose()


@pytest.fixture
def pinned_tags(monkeypatch):
    """Keep every tag a worker loads alive, as a live reference would.

    A session's identity map holds unmodified rows weakly, so in CPython a tag
    nobody references is freed as soon as apply_fill returns, and the next
    query loads it fresh. The stale read needs the row to stay alive in the
    worker's session: a reference held by a traceback in a log record, by a
    caller, or by anything else. Pinning them here stands in for that.
    """
    pinned = []
    real = book.get_order_tag

    def pinning_get_order_tag(orderid):
        tag = real(orderid)
        pinned.append(tag)
        return tag

    monkeypatch.setattr(book, "get_order_tag", pinning_get_order_tag)
    return pinned


def test_a_stale_worker_session_cannot_double_book_a_fill(own_book, pinned_tags):
    worker_a = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bus-a")
    worker_b = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bus-b")
    try:
        assert worker_a.submit(
            book.record_order_tag, "ord-1", "u1", "gt-strategy", "NIFTY30SEP2624000CE", "NFO", "NRML"
        ).result(30)

        # Worker A books 50. Worker B then sees a duplicate 50, books nothing,
        # and before the fix kept the tag (watermark 50) in its session.
        assert worker_a.submit(book.apply_fill, "ord-1", 50, 100.0, "BUY").result(30)
        assert worker_b.submit(book.apply_fill, "ord-1", 50, 100.0, "BUY").result(30) is None

        # Worker A books the next 50 (watermark 100). A duplicate 100 on B must
        # read 100, not its stale 50.
        first = worker_a.submit(book.apply_fill, "ord-1", 100, 100.0, "BUY").result(30)
        assert first is not None and first["booked_quantity"] == 50
        assert worker_b.submit(book.apply_fill, "ord-1", 100, 100.0, "BUY").result(30) is None
    finally:
        worker_a.shutdown(wait=True)
        worker_b.shutdown(wait=True)

    leg = own_book.query(book.StrategyPosition).filter_by(strategy="gt-strategy").one()
    assert leg.quantity == 100  # before the fix: 150
    tag = own_book.query(book.StrategyOrderTag).filter_by(orderid="ord-1").one()
    assert tag.applied_quantity == 100
    own_book.remove()


def test_a_fill_that_beat_its_tag_is_still_booked_once(own_book):
    assert book.apply_fill("ord-2", 25, 200.0, "SELL") is None  # buffered
    assert book.record_order_tag("ord-2", "u1", "gt-strategy", "BANKNIFTY", "NFO", "NRML")
    leg = own_book.query(book.StrategyPosition).filter_by(symbol="BANKNIFTY").one()
    assert leg.quantity == -25
    assert own_book.query(book.StrategyPendingFill).filter_by(orderid="ord-2").count() == 0
    own_book.remove()


class RecordingBus:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, topic, callback, name="", critical=False):
        self.subscriptions.append((topic, name, critical))


def test_the_book_subscribers_run_on_the_critical_lane():
    bus = RecordingBus()
    book_subscriber.register(bus)

    assert bus.subscriptions, "nothing was registered"
    assert all(critical for _topic, _name, critical in bus.subscriptions), bus.subscriptions
    topics = {topic for topic, _name, _critical in bus.subscriptions}
    assert {"order.placed", "order.update", "basket.completed"} <= topics


def test_critical_book_callbacks_survive_a_best_effort_backlog():
    import threading

    from utils.event_bus import Event, EventBus

    bus = EventBus(workers=1, max_pending=10, critical_workers=2, critical_max_pending=5000)
    release = threading.Event()
    seen = []
    seen_lock = threading.Lock()

    def slow_alert(_event):
        release.wait(10)

    def book_fill(event):
        with seen_lock:
            seen.append(event)

    bus.subscribe("order.update", slow_alert, name="alert")
    bus.subscribe("order.update", book_fill, name="StrategyBookFills", critical=True)
    try:
        for _ in range(1500):
            bus.publish(Event(topic="order.update"))
        release.set()
        deadline = threading.Event()
        for _ in range(200):
            with seen_lock:
                if len(seen) == 1500:
                    break
            deadline.wait(0.05)
        assert len(seen) == 1500
    finally:
        release.set()
        bus._executor.shutdown(wait=True)
        bus._critical_executor.shutdown(wait=True)
