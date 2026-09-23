"""Smart orders on the 17 brokers_b plugins: one order per decision, and a fresh book.

A smart order reads the open position, works out the order that takes it to the
target size, and places it. Each of these plugins carries the same two guards:
a position book cached for a second and invalidated after every order, and a
per-symbol lock so two smart orders for one symbol run one after the other.

The defect pinned here existed under eventlet too. The cache used to store
whatever its fetch returned, even when an order had been placed, and the cache
invalidated, while that fetch was in flight. The next smart order then read the
book from before the fill and could repeat or reverse the order. The cache key
is the auth token, shared by every symbol, so the in-flight fetch can belong to
a smart order on a different symbol that the per-symbol lock does not serialise.

Every test runs against every plugin with the broker replaced by an in-memory
book: no account, no network.
"""

from __future__ import annotations

import importlib
import threading
import time
import uuid

import pytest

from utils import runtime

BROKERS = [
    "indmoney",
    "jainamxts",
    "kotak",
    "motilal",
    "mstock",
    "nubra",
    "paytm",
    "pocketful",
    "rmoney",
    "samco",
    "shoonya",
    "tradejini",
    "tradesmart",
    "upstox",
    "wisdom",
    "zebu",
    "zerodha",
]


class _Response:
    def __init__(self, status: int = 200):
        self.status = status
        self.status_code = status


class FakeBroker:
    """An in-memory position book standing in for the broker's REST API.

    ``get_positions`` returns a snapshot taken when the request arrives, the
    way a broker answers from its own book. ``block_fetch`` makes one numbered
    fetch wait on ``release`` after taking its snapshot, which is the window an
    order from another request lands in.
    """

    def __init__(self, order_delay: float = 0.0):
        self.book: dict[str, int] = {}
        self.orders: list[tuple[str, str, int]] = []
        self.fetches = 0
        self.order_delay = order_delay
        self.block_fetch: int | None = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def get_positions(self, auth, **_kwargs):
        with self._lock:
            self.fetches += 1
            number = self.fetches
            snapshot = dict(self.book)
        if number == self.block_fetch:
            self.entered.set()
            assert self.release.wait(10), "the blocked fetch was never released"
        return snapshot

    def place_order_api(self, data, auth):
        if self.order_delay:
            time.sleep(self.order_delay)
        quantity = int(data["quantity"])
        action = str(data["action"]).upper()
        with self._lock:
            self.orders.append((data["symbol"], action, quantity))
            signed = quantity if action == "BUY" else -quantity
            self.book[data["symbol"]] = self.book.get(data["symbol"], 0) + signed
            orderid = str(len(self.orders))
        return _Response(200), {"status": "success", "orderid": orderid}, orderid


@pytest.fixture(params=BROKERS)
def plugin(request, monkeypatch):
    """The broker's order_api module wired to a FakeBroker.

    ``get_open_position`` is replaced by one that reads the net quantity out
    of ``_get_cached_positions``, so the module's own cache sits between every
    smart order and the fake book, as it does against the real broker.
    """
    module = importlib.import_module(f"broker.{request.param}.api.order_api")
    fake = FakeBroker()

    def get_open_position(symbol, exchange, product, auth):
        return str(module._get_cached_positions(auth).get(symbol, 0))

    monkeypatch.setattr(module, "get_positions", fake.get_positions)
    # The fake book is a successful read by construction; the plugin's check
    # of a real reply is pinned per broker in test_position_read_failure.py.
    monkeypatch.setattr(module, "_position_book_ok", lambda _data: True)
    monkeypatch.setattr(module, "place_order_api", fake.place_order_api)
    monkeypatch.setattr(module, "get_open_position", get_open_position)
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    module.fake = fake
    yield module
    fake.release.set()
    del module.fake


def _auth() -> str:
    """A token no other test has cached against."""
    return f"tok-{uuid.uuid4().hex}"


def _smart(symbol: str, position_size: int, quantity: int = 0, action: str = "BUY") -> dict:
    return {
        "symbol": symbol,
        "exchange": "NSE",
        "product": "MIS",
        "pricetype": "MARKET",
        "action": action,
        "quantity": str(quantity),
        "position_size": str(position_size),
    }


def _in_thread(fn, *args):
    result: dict = {}

    def run():
        try:
            result["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - asserted by the caller
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, result


# --- brokers_b-01: the position book ----------------------------------------


def test_a_fetch_that_straddles_an_invalidation_is_not_cached(plugin):
    """The fetch is returned to its own caller, and the next read goes to the broker."""
    fake = plugin.fake
    auth = _auth()
    fake.book = {"SBIN": 50}
    fake.block_fetch = 1

    thread, result = _in_thread(plugin._get_cached_positions, auth)
    assert fake.entered.wait(5)
    fake.book = {"SBIN": 0}  # an order filled while the fetch was in flight
    plugin._invalidate_position_cache(auth)
    fake.release.set()
    thread.join(5)

    assert result.get("value") == {"SBIN": 50}, "the caller that asked first gets its own answer"
    assert plugin._get_cached_positions(auth) == {"SBIN": 0}
    assert fake.fetches == 2


def test_a_fresh_book_is_reused_within_its_second(plugin):
    """Unchanged behaviour: a burst of smart orders fetches the book once."""
    fake = plugin.fake
    auth = _auth()
    fake.book = {"SBIN": 5}
    first = plugin._get_cached_positions(auth)
    second = plugin._get_cached_positions(auth)
    assert first == second == {"SBIN": 5}
    assert fake.fetches == 1
    plugin._invalidate_position_cache(auth)
    plugin._get_cached_positions(auth)
    assert fake.fetches == 2


def test_an_exit_after_another_symbols_stale_fetch_still_closes_the_position(plugin):
    """The audited interleaving, end to end through place_smartorder_api.

    B (symbol Y) starts a position fetch. A (symbol X) buys 50 and invalidates
    the cache while B's fetch is in flight. B's answer, taken before A's order,
    arrives afterwards. C, a close alert for X, must see the 50 and sell it.
    Before the fix C read B's stale book, found no position, and placed
    nothing, leaving 50 open.
    """
    fake = plugin.fake
    auth = _auth()
    fake.block_fetch = 1

    b_thread, b_result = _in_thread(plugin.place_smartorder_api, _smart("Y", 0), auth)
    assert fake.entered.wait(5)

    plugin.place_smartorder_api(_smart("X", 50), auth)
    assert fake.orders == [("X", "BUY", 50)]

    fake.release.set()
    b_thread.join(5)
    assert "error" not in b_result, b_result.get("error")

    plugin.place_smartorder_api(_smart("X", 0), auth)
    assert fake.orders == [("X", "BUY", 50), ("X", "SELL", 50)]
    assert fake.book["X"] == 0


@pytest.mark.parametrize("gthread", [False, True], ids=["eventlet-or-dev", "gthread"])
def test_concurrent_smart_orders_for_one_symbol_place_exactly_one_order(
    plugin, monkeypatch, gthread
):
    """Eight alerts for the same target, released together: one order.

    Under gthread the wait for the symbol is bounded, but far above what
    these orders take, so every alert still waits its turn.
    """
    monkeypatch.setattr(runtime, "gthread_active", lambda: gthread)
    fake = plugin.fake
    fake.order_delay = 0.05
    auth = _auth()
    count = 8
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def worker():
        try:
            barrier.wait(5)
            plugin.place_smartorder_api(_smart("SBIN", 10), auth)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive(), "a smart order hung"

    assert errors == []
    assert fake.orders == [("SBIN", "BUY", 10)]
    assert fake.book == {"SBIN": 10}


# --- brokers_b-02: how long a smart order waits for its symbol -------------


def _hold_symbol(plugin, symbol: str = "SBIN"):
    """Hold the plugin's lock for ``symbol`` from another thread until released."""
    held = threading.Event()
    release = threading.Event()

    def holder():
        with plugin._get_symbol_lock(symbol, "NSE", "MIS") as acquired:
            assert acquired
            held.set()
            release.wait(10)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert held.wait(5)
    return thread, release


def test_under_gthread_a_smart_order_stops_waiting_and_sends_nothing(plugin, monkeypatch):
    """A queue of alerts behind one slow broker call must not hold a thread each."""
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(plugin._SMART_ORDER_LOCKS, "_max_wait", 0.2)
    holder, release = _hold_symbol(plugin)
    try:
        started = time.monotonic()
        res, data, orderid = plugin.place_smartorder_api(_smart("SBIN", 10), _auth())
        elapsed = time.monotonic() - started
    finally:
        release.set()
        holder.join(5)

    assert elapsed < 2.0
    assert res.status == 429 and res.status_code == 429
    assert data["status"] == "error"
    assert "SBIN" in data["message"]
    assert "429" not in data["message"], "a status code is not a message for a trader"
    assert orderid is None
    assert plugin.fake.orders == []
    assert plugin.fake.fetches == 0, "no position read either: the order was never started"


def test_outside_gthread_a_smart_order_waits_as_long_as_it_takes(plugin, monkeypatch):
    """Eventlet and the dev server keep the unbounded wait they always had."""
    monkeypatch.setattr(plugin._SMART_ORDER_LOCKS, "_max_wait", 0.2)
    holder, release = _hold_symbol(plugin)
    thread, result = _in_thread(plugin.place_smartorder_api, _smart("SBIN", 10), _auth())
    try:
        time.sleep(0.6)
        assert thread.is_alive(), "the smart order gave up although gthread is not active"
        assert plugin.fake.orders == []
    finally:
        release.set()
        holder.join(5)
    thread.join(5)
    assert "error" not in result, result.get("error")
    assert plugin.fake.orders == [("SBIN", "BUY", 10)]


# --- gap-05: the lock registry ----------------------------------------------


def test_the_lock_registry_forgets_every_symbol_it_served(plugin):
    """One lock per instrument ever traded used to stay for the life of the worker."""
    auth = _auth()
    for index in range(2000):
        plugin.place_smartorder_api(_smart(f"SYM{index}", 0), auth)
    assert len(plugin._SMART_ORDER_LOCKS) == 0
    assert plugin.fake.orders == []
