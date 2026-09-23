"""Smart orders across every brokers_a plugin: one order per decision, bounded waits.

A smart order reads the open position for its symbol, works out the order that
takes it to the target size and places it, all under a per-symbol lock. Three
properties are pinned here for each of the eighteen brokers, with the broker's
HTTP layer replaced by an in-memory position book:

* **Two concurrent smart orders for one symbol place exactly one order.** The
  second must wait for the first, then read the book after its fill and find
  nothing left to do.
* **The symbol lock registry forgets a symbol once nobody holds it.** The old
  registries kept one lock per symbol ever traded for the life of the worker.
* **Under the gthread worker a waiter gives up** after the bound and returns a
  refusal a trader can read, rather than holding a request thread behind a
  slow broker; no second order is sent. **Under eventlet and the dev server it
  waits as long as it takes**, exactly as before.
"""

from __future__ import annotations

import gc
import importlib
import os
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from utils import runtime
from utils.smart_order_guard import SMART_ORDER_BUSY_MESSAGE, SymbolLocks

os.environ.setdefault("BROKER_API_KEY", "client:::key:::secret")

BROKERS = [
    "aliceblue",
    "angel",
    "arrow",
    "compositedge",
    "definedge",
    "deltaexchange",
    "dhan",
    "dhan_sandbox",
    "firstock",
    "fivepaisa",
    "fivepaisaxts",
    "flattrade",
    "fyers",
    "groww",
    "hdfcsecurities",
    "hdfcsky",
    "ibulls",
    "iifl",
]

#: The bound used by the gthread cases, short so the suite stays fast.
SHORT_BOUND = 0.3


class FakeBroker:
    """An in-memory position book and order endpoint for one symbol."""

    def __init__(self, hold: threading.Event | None = None):
        self.qty = 0
        self.orders: list[tuple[str, int]] = []
        self.lock = threading.Lock()
        self.hold = hold
        self.placing = threading.Event()

    def get_positions(self, auth):
        with self.lock:
            return {"qty": self.qty}

    def place_order_api(self, data, auth):
        self.placing.set()
        if self.hold is not None:
            assert self.hold.wait(20), "the test never released the broker"
        # Delta Exchange sizes in floats ("5.0"); everyone else in integers.
        qty = int(float(data["quantity"]))
        with self.lock:
            self.qty += qty if data["action"] == "BUY" else -qty
            self.orders.append((data["action"], qty))
            number = len(self.orders)
        res = SimpleNamespace(status=200, status_code=200)
        return res, {"status": "success", "orderid": str(number)}, str(number)


def _wire(monkeypatch, module, broker: FakeBroker):
    """Route the module's position read and order call to the fake broker."""
    monkeypatch.setattr(module, "get_positions", broker.get_positions)
    monkeypatch.setattr(module, "place_order_api", broker.place_order_api)

    def get_open_position(*args, **kwargs):
        # The auth token is the last argument everywhere (5paisa passes six).
        auth = kwargs.get("auth", args[-1] if args else None)
        return str(module._get_cached_positions(auth)["qty"])

    monkeypatch.setattr(module, "get_open_position", get_open_position)


def _order(position_size=5, quantity=5, action="BUY", symbol="SBIN"):
    return {
        "apikey": "test",
        "strategy": "test",
        "symbol": symbol,
        "exchange": "NSE",
        "product": "MIS",
        "action": action,
        "quantity": str(quantity),
        "position_size": str(position_size),
        "pricetype": "MARKET",
        "price": "0",
        "trigger_price": "0",
        "disclosed_quantity": "0",
    }


def _shorten_bound(monkeypatch, module, broker_name):
    if broker_name == "aliceblue":
        monkeypatch.setattr(module, "SMART_ORDER_LOCK_WAIT_SECONDS", SHORT_BOUND)
    else:
        monkeypatch.setattr(module, "_symbol_locks", SymbolLocks(max_wait=SHORT_BOUND, name="test"))


@contextmanager
def _hold(module, broker_name, symbol, exchange="NSE", product="MIS"):
    """Hold a symbol lock the way that broker's place_smartorder_api does."""
    if broker_name == "aliceblue":
        lock = module._get_symbol_lock(symbol, exchange, product)
        with lock:
            yield
    else:
        with module._get_symbol_lock(symbol, exchange, product) as acquired:
            assert acquired
            yield


def _registry_size(module, broker_name):
    gc.collect()
    if broker_name == "aliceblue":
        return len(list(module._symbol_locks.keys()))
    return len(module._symbol_locks)


@pytest.fixture(params=BROKERS)
def broker(request):
    module = importlib.import_module(f"broker.{request.param}.api.order_api")
    module._invalidate_position_cache("tok")
    yield request.param, module
    module._invalidate_position_cache("tok")


@pytest.fixture
def gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)


@pytest.fixture
def not_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)


def _run_together(count, target):
    barrier = threading.Barrier(count)
    results: list = [None] * count
    errors: list = []

    def runner(index):
        try:
            barrier.wait(10)
            results[index] = target(index)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive(), "a smart order hung"
    assert errors == [], errors[:3]
    return results


# --- one order per decision ---------------------------------------------------


@pytest.mark.parametrize("mode", ["gthread", "not_gthread"])
def test_two_concurrent_smart_orders_for_one_symbol_place_one_order(
    broker, mode, monkeypatch, request
):
    request.getfixturevalue(mode)
    name, module = broker
    fake = FakeBroker()
    _wire(monkeypatch, module, fake)

    results = _run_together(2, lambda _i: module.place_smartorder_api(_order(), "tok"))

    assert fake.orders == [("BUY", 5)], f"{name} placed {fake.orders}"
    assert fake.qty == 5
    placed = [r for r in results if r[0] is not None]
    assert len(placed) == 1


def test_a_burst_of_identical_alerts_places_one_order(broker, monkeypatch):
    """Eight copies of one TradingView alert: one order, seven no-ops."""
    name, module = broker
    fake = FakeBroker()
    _wire(monkeypatch, module, fake)

    _run_together(8, lambda _i: module.place_smartorder_api(_order(), "tok"))

    assert fake.orders == [("BUY", 5)], f"{name} placed {fake.orders}"


def test_a_smart_order_after_a_fill_sizes_itself_against_the_new_book(broker, monkeypatch):
    name, module = broker
    fake = FakeBroker()
    _wire(monkeypatch, module, fake)

    module.place_smartorder_api(_order(position_size=5, quantity=5), "tok")
    module.place_smartorder_api(_order(position_size=0, quantity=0, action="SELL"), "tok")

    assert fake.orders == [("BUY", 5), ("SELL", 5)], f"{name} placed {fake.orders}"
    assert fake.qty == 0


# --- the registry ---------------------------------------------------------------


def test_the_symbol_lock_registry_forgets_idle_symbols(broker):
    name, module = broker
    before = _registry_size(module, name)

    def worker(index):
        for n in range(125):
            with _hold(module, name, f"SYM{index}_{n}"):
                pass

    _run_together(8, worker)
    assert _registry_size(module, name) == before == 0


def test_a_held_symbol_lock_is_shared_not_duplicated(broker, not_gthread):
    """While one caller holds a symbol a second must wait on the same lock."""
    name, module = broker
    inside = threading.Event()
    release = threading.Event()
    order = []

    def holder():
        with _hold(module, name, "RELIANCE"):
            order.append("holder in")
            inside.set()
            assert release.wait(10)
            order.append("holder out")

    def waiter():
        assert inside.wait(10)
        with _hold(module, name, "RELIANCE"):
            order.append("waiter in")

    threads = [threading.Thread(target=holder), threading.Thread(target=waiter)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    assert order == ["holder in"], "the waiter got in while the symbol was held"
    release.set()
    for thread in threads:
        thread.join(10)
    assert order == ["holder in", "holder out", "waiter in"]
    assert _registry_size(module, name) == 0


# --- the bounded wait -----------------------------------------------------------


def test_under_gthread_a_waiter_gives_up_and_sends_nothing(broker, gthread, monkeypatch):
    name, module = broker
    _shorten_bound(monkeypatch, module, name)
    release = threading.Event()
    fake = FakeBroker(hold=release)
    _wire(monkeypatch, module, fake)

    first = {}
    holder = threading.Thread(
        target=lambda: first.setdefault("result", module.place_smartorder_api(_order(), "tok"))
    )
    holder.start()
    assert fake.placing.wait(10), "the first smart order never reached the broker"

    started = time.monotonic()
    res, data, orderid = module.place_smartorder_api(_order(), "tok")
    waited = time.monotonic() - started

    release.set()
    holder.join(10)

    assert waited < SHORT_BOUND + 2, f"{name} waited {waited:.1f}s past the bound"
    assert res.status == 429 and res.status_code == 429
    assert orderid is None
    assert data == {
        "status": "error",
        "message": SMART_ORDER_BUSY_MESSAGE.format(symbol="SBIN"),
    }
    assert fake.orders == [("BUY", 5)], "a refused smart order still reached the broker"
    assert first["result"][2] == "1"
    assert _registry_size(module, name) == 0


def test_outside_gthread_a_waiter_waits_past_the_bound(broker, not_gthread, monkeypatch):
    """Eventlet and the dev server keep the unbounded wait they always had."""
    name, module = broker
    _shorten_bound(monkeypatch, module, name)
    release = threading.Event()
    fake = FakeBroker(hold=release)
    _wire(monkeypatch, module, fake)

    first = {}
    holder = threading.Thread(
        target=lambda: first.setdefault("result", module.place_smartorder_api(_order(), "tok"))
    )
    holder.start()
    assert fake.placing.wait(10)

    second = {}
    waiter = threading.Thread(
        target=lambda: second.setdefault("result", module.place_smartorder_api(_order(), "tok"))
    )
    waiter.start()
    time.sleep(SHORT_BOUND * 3)
    assert waiter.is_alive(), f"{name} gave up waiting outside the gthread worker"

    release.set()
    holder.join(10)
    waiter.join(10)
    assert not waiter.is_alive()
    res, data, orderid = second["result"]
    # It waited, then read the book after the first fill: nothing to do.
    assert res is None and orderid is None
    assert data["status"] == "success"
    assert fake.orders == [("BUY", 5)]


# --- under a real eventlet hub ------------------------------------------------

EVENTLET_SCRIPT = """
import eventlet
eventlet.monkey_patch()
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.main.load_dotenv = dotenv.load_dotenv

import importlib
from types import SimpleNamespace

from utils import runtime
from utils.smart_order_guard import SymbolLocks

assert runtime.worker_class() == "eventlet" and not runtime.gthread_active()
results = {}
for name in ("dhan", "aliceblue", "flattrade"):
    module = importlib.import_module(f"broker.{name}.api.order_api")
    # A bound far shorter than the hold: under eventlet it must not apply.
    if name == "aliceblue":
        module.SMART_ORDER_LOCK_WAIT_SECONDS = 0.1
    else:
        module._symbol_locks = SymbolLocks(max_wait=0.1, name="test")
    book = {"qty": 0}
    orders = []

    def place_order_api(data, auth, book=book, orders=orders):
        eventlet.sleep(0.5)  # the broker round trip, yielding to the hub
        book["qty"] += int(float(data["quantity"]))
        orders.append(data["action"])
        return SimpleNamespace(status=200, status_code=200), {"status": "success"}, "1"

    def get_open_position(*args, module=module):
        return str(module._get_cached_positions(args[-1])["qty"])

    module.place_order_api = place_order_api
    module.get_positions = lambda auth, book=book: dict(book)
    module.get_open_position = get_open_position
    order = {
        "symbol": "SBIN", "exchange": "NSE", "product": "MIS", "action": "BUY",
        "quantity": "5", "position_size": "5", "pricetype": "MARKET", "price": "0",
    }
    first = eventlet.spawn(module.place_smartorder_api, dict(order), "tok")
    eventlet.sleep(0.05)
    second = eventlet.spawn(module.place_smartorder_api, dict(order), "tok")
    outcomes = [first.wait(), second.wait()]
    statuses = [getattr(res, "status", None) for res, _data, _oid in outcomes]
    results[name] = (orders, statuses)

for name, (orders, statuses) in results.items():
    assert orders == ["BUY"], (name, orders)
    assert 429 not in statuses, (name, statuses)
print("OK")
"""


@pytest.mark.skipif(
    __import__("importlib.util").util.find_spec("eventlet") is None,
    reason="eventlet is installed by the production installer, not on Windows dev",
)
def test_under_real_eventlet_a_waiter_waits_past_any_bound(tmp_path):
    """The production default: green waiters queue as they always did."""
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    db = tmp_path / "db"
    db.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "BROKER_API_KEY": "client:::key:::secret",
            "PYTHONPATH": str(repo),
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(EVENTLET_SCRIPT)],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "OK" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-4000:]
