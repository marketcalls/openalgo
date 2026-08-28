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
