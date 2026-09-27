"""Real OS-thread primitives, for state shared with a non-greenlet thread.

Under gunicorn+eventlet ``threading.Lock``, ``RLock`` and ``Event`` are green:
they belong to the hub and can only be handed from one greenlet to another.
Sharing one with a real OS thread is not merely slow, it deadlocks. The hub
tries to resume a waiter that lives in another thread, raises

    greenlet.error: Cannot switch to a different thread

inside ``fire_timers``, and leaves that thread blocked on the lock forever.

The thread that matters is the asyncio loop in ``services/websocket_client.py``:
it must be a real one because ``asyncio`` cannot run on a green thread, and it
invokes every registered market-data, auth and error callback. So anything
those callbacks touch is shared across the two worlds and belongs here.

Only the dev server escapes it, because ``uv run app.py`` never patches
anything, which is why this class of bug passes every local test and only
appears in production.

**Keep the critical section short.** A greenlet blocking on a real lock blocks
the whole hub until it is released, so guard in-memory bookkeeping and do the
database and network work after the release.

Where eventlet is absent these are simply the stdlib primitives.
"""

import queue
import sys
import threading
import time

if "eventlet" in sys.modules:
    import eventlet

    _threading = eventlet.patcher.original("threading")
    _queue = eventlet.patcher.original("queue")
else:
    _threading = threading
    _queue = queue

Lock = _threading.Lock
RLock = _threading.RLock
Event = _threading.Event
Thread = _threading.Thread
Condition = _threading.Condition

#: A real queue, for handing work from a real OS thread to the hub. Drain it
#: with get_nowait() from a greenlet; a blocking get() would freeze the hub.
Queue = _queue.Queue
Empty = _queue.Empty


def wait_for(event, timeout, poll=0.02):
    """Wait for an Event another OS thread will set, without freezing the hub.

    Neither primitive is usable directly for a wait of any length:

    * a green Event never wakes on a ``set()`` from a real OS thread, so the
      waiter sits out its entire timeout and reports failure for something that
      arrived on time;
    * a real Event wakes correctly, but ``Event.wait()`` blocks, and a greenlet
      blocking stops the hub -- every other request on this worker -- for the
      whole wait.

    Polling a real Event keeps both properties. ``is_set()`` only reads a flag,
    and the sleep between checks is eventlet's, so the greenlet yields.

    Pass a real Event (``Event`` from this module). Returns True if it was set
    before the timeout, matching ``Event.wait``.
    """
    deadline = time.monotonic() + timeout
    while not event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(poll, remaining))
    return True


def join(thread, timeout=None, poll=0.02):
    """Wait for a real OS thread to finish without freezing the hub.

    ``Thread.join()`` on a real thread blocks, and a greenlet blocking stops
    every other request on the worker for the whole wait. Polling ``is_alive``
    costs a flag read and yields in between.

    Joining a *green* thread needs none of this: eventlet's own join already
    yields. This is only for threads created from ``Thread`` in this module.

    Returns True if the thread finished, False if the timeout ran out, so a
    caller can tell the difference the way ``is_alive()`` after ``join()`` does.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    while thread.is_alive():
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(poll)
    return True


__all__ = [
    "Condition",
    "Empty",
    "Event",
    "Lock",
    "Queue",
    "RLock",
    "Thread",
    "join",
    "wait_for",
]
