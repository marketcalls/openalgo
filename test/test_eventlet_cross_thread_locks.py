"""State shared with the websocket client's OS thread needs a real lock.

`services/websocket_client.py` runs its asyncio loop on a real OS thread,
because asyncio cannot run on a green one, and it invokes every registered
market-data, auth and error callback from that thread. Under gunicorn+eventlet
`threading.Lock` is a green semaphore owned by the hub, so a lock those
callbacks share with the request path spans two worlds. Contended, the hub
tries to resume a waiter belonging to another thread and raises

    greenlet.error: Cannot switch to a different thread

inside `fire_timers`, leaving the loop thread blocked on that lock forever. The
websocket feed then stops answering pings and resolving subscribe acks, so
every later subscribe waits out its full timeout -- which is what a user sees
as "the first order works and the second one hangs the app".

Only production hits it: `uv run app.py` never patches anything, so every one
of these cases passes locally whatever the lock is made of. That is why the
proof runs under a real eventlet hub rather than being asserted about the
source.

Each case runs in a subprocess. `eventlet.monkey_patch()` is global and cannot
be undone, so importing it into the pytest process would change the meaning of
every test that ran afterwards.
"""

import subprocess
import sys
import textwrap

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import threading, time
import eventlet.patcher

_orig = eventlet.patcher.original("threading")


def contend(lock, hold=0.3, wait=5.0):
    '''A greenlet holds `lock` and yields; a real OS thread then wants it.

    Returns True if the real thread ever got it. The wait is cooperative:
    Thread.join() from a greenlet is itself a blocking call that would freeze
    the hub and make a starved thread look like a deadlocked one.
    '''
    got = []

    def real_thread_side():
        with lock:
            got.append(1)

    def greenlet_side():
        with lock:
            eventlet.sleep(hold)

    g = eventlet.spawn(greenlet_side)
    eventlet.sleep(0.05)
    t = _orig.Thread(target=real_thread_side, daemon=True)
    t.start()
    deadline = time.monotonic() + wait
    while t.is_alive() and time.monotonic() < deadline:
        eventlet.sleep(0.02)
    g.wait()
    return bool(got)
"""


def run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_green_lock_deadlocks_the_loop_thread():
    """The defect itself, so the rest of this file cannot pass vacuously."""
    result = run(
        """
        assert contend(threading.Lock()) is False, (
            "a green lock let a real OS thread through; eventlet may no longer "
            "patch threading.Lock, which would make this whole file moot"
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_the_shared_primitives_let_the_loop_thread_through():
    result = run(
        """
        import utils.real_threading as rt

        assert contend(rt.Lock()), "real lock still blocked the OS thread"
        assert contend(rt.RLock()), "real RLock still blocked the OS thread"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_waiting_on_a_tick_wakes_on_time_without_freezing_the_hub():
    """`flow_executor_service` waits for a tick its callback delivers from the
    loop thread. Both obvious primitives fail, in opposite directions: a green
    Event never wakes at all, and a real Event's blocking wait() stops every
    other request on the worker until it returns. Only the polled form does
    both jobs, so this measures both properties rather than just the return
    value -- an Event set before the timeout returns True either way.
    """
    result = run(
        """
        import utils.real_threading as rt

        SET_AT, TIMEOUT = 0.3, 3.0

        def measure(wait_call):
            ticks = []

            def hub_alive():
                while True:
                    ticks.append(1)
                    eventlet.sleep(0.02)

            g = eventlet.spawn(hub_alive)
            event = rt.Event() if wait_call is not None else threading.Event()
            _orig.Thread(target=lambda: (time.sleep(SET_AT), event.set()),
                         daemon=True).start()
            t0 = time.monotonic()
            before = len(ticks)
            woke = wait_call(event) if wait_call else event.wait(timeout=TIMEOUT)
            g.kill()
            return woke, time.monotonic() - t0, len(ticks) - before

        woke, took, ticks = measure(None)
        assert not woke and took >= TIMEOUT - 0.2, (
            f"green Event: expected it to sit out the timeout, got "
            f"woke={woke} after {took:.2f}s"
        )

        woke, took, ticks = measure(lambda e: e.wait(timeout=TIMEOUT))
        assert woke and ticks == 0, (
            f"real Event.wait(): expected the hub to be frozen, got {ticks} ticks"
        )

        woke, took, ticks = measure(lambda e: rt.wait_for(e, TIMEOUT))
        assert woke, "wait_for did not see the set"
        assert took < SET_AT + 0.3, f"wait_for woke late, after {took:.2f}s"
        assert ticks > 5, f"wait_for froze the hub: only {ticks} ticks"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_the_locks_that_cross_the_boundary_are_real():
    """Guards the specific attributes, so a later edit back to threading.Lock
    fails here rather than in production."""
    result = run(
        """
        import utils.real_threading as rt
        from services.websocket_client import WebSocketClient
        from sandbox.websocket_execution_engine import WebSocketExecutionEngine

        green = type(threading.Lock())

        client = WebSocketClient("test-key")
        assert not isinstance(client.lock, green), (
            "WebSocketClient.lock is green; _handle_message takes it on the "
            "asyncio loop's OS thread"
        )

        engine = WebSocketExecutionEngine()
        assert not isinstance(engine._lock, green), (
            "sandbox engine _lock is green; _on_market_data takes it on the "
            "asyncio loop's OS thread"
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_joining_a_real_thread_does_not_freeze_the_hub():
    """`Thread.join()` on a real OS thread blocks, and a greenlet blocking stops
    every other request on the worker. Reached from the /telegram stop route and
    from websocket client teardown, both greenlet contexts."""
    result = run(
        """
        import utils.real_threading as rt

        RUNS_FOR = 0.4

        def measure(joiner):
            ticks = []

            def hub_alive():
                while True:
                    ticks.append(1)
                    eventlet.sleep(0.02)

            g = eventlet.spawn(hub_alive)
            t = rt._threading.Thread(target=lambda: time.sleep(RUNS_FOR), daemon=True)
            t.start()
            eventlet.sleep(0.05)
            before, t0 = len(ticks), time.monotonic()
            finished = joiner(t)
            took, during = time.monotonic() - t0, len(ticks) - before
            g.kill()
            return finished, took, during

        _, took, ticks = measure(lambda t: t.join(timeout=5) or not t.is_alive())
        assert ticks <= 1, f"expected a blocking join to freeze the hub, got {ticks} ticks"

        finished, took, ticks = measure(lambda t: rt.join(t, timeout=5))
        assert finished, "cooperative join did not see the thread finish"
        assert took < RUNS_FOR + 0.3, f"woke late, after {took:.2f}s"
        assert ticks > 5, f"cooperative join froze the hub: only {ticks} ticks"

        # A timeout must still be honoured, and reported.
        slow = rt._threading.Thread(target=lambda: time.sleep(5), daemon=True)
        slow.start()
        t0 = time.monotonic()
        assert rt.join(slow, timeout=0.3) is False, "expected False on timeout"
        assert time.monotonic() - t0 < 1.0, "timeout not honoured"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_subscriber_callbacks_never_run_on_the_websocket_loop_thread():
    """The loop thread must only enqueue.

    Its callbacks reach SocketIO, the event bus and the sandbox engine, all of
    which use eventlet primitives, so calling them from the asyncio OS thread
    is the crossing reported in #1402, #1473 and #1569. The loop thread hands
    the payload over and a green thread does the calling.
    """
    result = run(
        """
        import threading as _t
        from services.websocket_client import WebSocketClient

        client = WebSocketClient("test-key")
        client.running = True

        seen = {}

        def on_tick(data):
            seen["thread"] = _t.current_thread().name
            seen["data"] = data

        client.register_callback("market_data", on_tick)

        # The dispatcher is a plain Thread, i.e. green under eventlet.
        dispatcher = _t.Thread(target=client._run_dispatch_loop, daemon=True)
        dispatcher.start()

        loop_thread_name = {}

        def loop_thread_side():
            loop_thread_name["name"] = _t.current_thread().name
            client._dispatch("market_data", {"symbol": "RELIANCE"})

        t = _orig.Thread(target=loop_thread_side, name="fake-asyncio-loop", daemon=True)
        t.start()

        deadline = time.monotonic() + 5
        while "data" not in seen and time.monotonic() < deadline:
            eventlet.sleep(0.02)
        client.running = False

        assert seen.get("data") == {"symbol": "RELIANCE"}, f"callback never ran: {seen}"
        assert seen["thread"] != loop_thread_name["name"], (
            f"callback ran on the loop thread ({seen['thread']}), which is the defect"
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_the_dispatch_queue_is_bounded():
    """The feed never blocks, so an unbounded queue grows until the worker is
    OOM-killed if a subscriber stalls."""
    result = run(
        """
        from services.websocket_client import WebSocketClient

        client = WebSocketClient("test-key")
        assert client.DISPATCH_QUEUE_MAX > 0
        for _ in range(client.DISPATCH_QUEUE_MAX + 500):
            client._dispatch("market_data", {"x": 1})

        assert client._dispatch_queue.qsize() <= client.DISPATCH_QUEUE_MAX, (
            "queue grew past its bound"
        )
        assert client._dispatch_dropped >= 500, (
            f"expected drops to be counted, got {client._dispatch_dropped}"
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


def test_a_result_from_the_loop_thread_wakes_its_caller_promptly():
    """`concurrent.futures.Future.result()` cannot be woken across the boundary.

    The future resolves correctly, but the waiting greenlet is never notified,
    so it sleeps until its own timeout expires and only then reads the value
    that was ready all along. That is why a subscribe took its full 12 seconds
    whenever it had to wait at all. This asserts on the elapsed time, not the
    value, because the value was always right.
    """
    result = run(
        """
        import asyncio
        from services.websocket_client import WebSocketClient

        client = WebSocketClient("test-key")
        ready = _orig.Event()

        def run_loop():
            client.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(client.loop)
            ready.set()
            client.loop.run_forever()

        _orig.Thread(target=run_loop, daemon=True).start()
        ready.wait()

        ticks = []

        def hub_alive():
            while True:
                ticks.append(1)
                eventlet.sleep(0.02)

        g = eventlet.spawn(hub_alive)
        eventlet.sleep(0.1)

        ARRIVES_AT, TIMEOUT = 0.3, 10.0

        async def ack():
            await asyncio.sleep(ARRIVES_AT)
            return {"status": "success"}

        before, t0 = len(ticks), time.monotonic()
        value = client._run_on_loop(ack(), timeout=TIMEOUT)
        took, during = time.monotonic() - t0, len(ticks) - before
        g.kill()

        assert value == {"status": "success"}, value
        assert took < ARRIVES_AT + 0.5, (
            f"took {took:.2f}s for a result ready at {ARRIVES_AT}s; the caller "
            f"is waiting out its timeout instead of being woken"
        )
        assert during > 5, f"hub was frozen: only {during} ticks"

        # The timeout must still be real, and errors must still propagate.
        async def slow():
            await asyncio.sleep(30)

        t0 = time.monotonic()
        try:
            client._run_on_loop(slow(), timeout=0.4)
            raise AssertionError("expected TimeoutError")
        except TimeoutError:
            pass
        assert time.monotonic() - t0 < 2, "timeout not honoured"

        async def boom():
            raise ValueError("propagated")

        try:
            client._run_on_loop(boom(), timeout=5)
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "propagated" in str(exc)
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr
