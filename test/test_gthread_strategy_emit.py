"""Socket.IO emits from the trading services start no thread per emit.

``socketio.start_background_task(socketio.emit, ...)`` with Flask-SocketIO's
threading async mode starts a new OS thread for every emit. The strategy
broadcast alone can send ten deltas a second per watched strategy, and two
threads can deliver them to the browser out of order, so an older P&L frame
overwrites a newer one. The emits are now made on the caller's thread, which
``extensions.SerializedSocketIO`` serialises under gthread and the development
server. Under eventlet a greenlet emits directly, as the background greenlet
used to, and a real OS thread hands the emit to the hub.
"""

import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from services.strategy_module import broadcast, state

ROOT = Path(__file__).resolve().parents[1]

EMITTING_FILES = [
    "services/orderstatus_service.py",
    "services/openposition_service.py",
    "services/order_router_service.py",
    "services/strategy_module/broadcast.py",
]


def test_no_trading_service_starts_a_background_task_to_emit():
    for rel in EMITTING_FILES:
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "start_background_task(" not in source, rel


class _CountingThreads:
    def __init__(self, monkeypatch):
        self.started = 0
        real_start = threading.Thread.start
        counter = self

        def start(thread_self, *args, **kwargs):
            counter.started += 1
            return real_start(thread_self, *args, **kwargs)

        monkeypatch.setattr(threading.Thread, "start", start)


class _FakeManager:
    def __init__(self):
        self.rooms = {"/": {}}


class _FakeSocketIO:
    def __init__(self):
        self.server = type("S", (), {"manager": _FakeManager()})()
        self.emits = []

    def emit(self, event, payload, **kwargs):
        self.emits.append((event, payload, kwargs, threading.get_ident()))


def test_a_strategy_delta_is_emitted_on_the_callers_thread(monkeypatch):
    fake = _FakeSocketIO()
    fake.server.manager.rooms["/"]["strategy:9101"] = {"sid": "eio"}
    monkeypatch.setattr(broadcast, "socketio", fake)
    state.init_run_state(
        9101001,
        9101,
        [
            {
                "leg_id": 1,
                "position": "B",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    counting = _CountingThreads(monkeypatch)
    try:
        assert broadcast.push_delta(9101001, force=True) is True
        assert broadcast.push_terminal(9101, 9101001, "manual", 0.0) is True
    finally:
        state.clear_run_state(9101001)

    assert counting.started == 0
    assert [event for event, *_rest in fake.emits] == [
        broadcast.EVENT_DELTA,
        broadcast.EVENT_TERMINAL,
    ]
    assert {ident for *_rest, ident in fake.emits} == {threading.get_ident()}


def test_an_analyzer_update_is_emitted_on_the_callers_thread(monkeypatch):
    import extensions
    import services.openposition_service as openposition_service
    import services.orderstatus_service as orderstatus_service

    seen = []
    monkeypatch.setattr(
        extensions.socketio, "emit", lambda event, data, **kw: seen.append((event, data))
    )
    counting = _CountingThreads(monkeypatch)

    orderstatus_service._emit_analyzer_update({"request": {}, "response": {"x": 1}})
    openposition_service._emit_analyzer_update({"request": {}, "response": {"x": 2}})

    assert counting.started == 0
    assert seen == [
        ("analyzer_update", {"request": {}, "response": {"x": 1}}),
        ("analyzer_update", {"request": {}, "response": {"x": 2}}),
    ]


def test_a_failing_analyzer_emit_never_reaches_the_service(monkeypatch):
    import extensions
    import services.orderstatus_service as orderstatus_service

    def boom(*_args, **_kwargs):
        raise RuntimeError("socket gone")

    monkeypatch.setattr(extensions.socketio, "emit", boom)

    orderstatus_service._emit_analyzer_update({"request": {}, "response": {}})


def test_a_queued_order_notification_is_emitted_on_the_callers_thread(monkeypatch):
    import services.order_router_service as order_router_service

    seen = []
    monkeypatch.setattr(order_router_service, "verify_api_key", lambda api_key: "u")
    monkeypatch.setattr(order_router_service, "create_pending_order", lambda *a: 91)
    monkeypatch.setattr(
        order_router_service,
        "emit_from_any_thread",
        lambda event, data, **kw: seen.append((event, threading.get_ident())),
    )
    counting = _CountingThreads(monkeypatch)

    ok, body, code = order_router_service.queue_order("k", {"strategy": "s"}, "placeorder")

    assert ok and code == 200 and body["pending_order_id"] == 91
    assert counting.started == 0
    assert seen == [("pending_order_created", threading.get_ident())]


# ---------------------------------------------------------------------------
# Under eventlet
# ---------------------------------------------------------------------------


EVENTLET_BODY = """
import eventlet
eventlet.monkey_patch()

import threading, time

import utils.real_threading as rt
assert rt.start_hub_worker()

import restx_api  # noqa: F401
from services.strategy_module import broadcast


class Fake:
    def __init__(self):
        self.calls = []

    def emit(self, event, payload, **kwargs):
        self.calls.append((event, rt.on_hub_thread()))


fake = Fake()
broadcast.socketio = fake

# A greenlet emits directly, on the hub, as the background greenlet used to.
broadcast._hand_to_server("from-greenlet", {}, "strategy:1")
assert fake.calls == [("from-greenlet", True)], fake.calls

# A real OS thread must not touch the server itself: its emit is queued for
# the hub, and the hub stays responsive while it waits.
done = rt.Event()

def real_side():
    broadcast._hand_to_server("from-real-thread", {}, "strategy:1")
    done.set()

thread = rt.Thread(target=real_side, daemon=True)
thread.start()
assert rt.wait_for(done, 5)
deadline = time.monotonic() + 5
while len(fake.calls) < 2 and time.monotonic() < deadline:
    eventlet.sleep(0.01)
assert fake.calls == [("from-greenlet", True), ("from-real-thread", True)], fake.calls
print("OK")
"""


def test_under_eventlet_a_greenlet_emits_directly_and_a_real_thread_hands_over():
    pytest.importorskip(
        "eventlet",
        reason="eventlet is installed by the production installer, not by pyproject",
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(EVENTLET_BODY)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert "OK" in result.stdout, result.stderr[-4000:]
