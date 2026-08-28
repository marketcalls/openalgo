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

import sys
import threading
import time

if "eventlet" in sys.modules:
    import eventlet

    _threading = eventlet.patcher.original("threading")
else:
    _threading = threading

Lock = _threading.Lock
RLock = _threading.RLock
Event = _threading.Event
Thread = _threading.Thread
Condition = _threading.Condition


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


__all__ = ["Condition", "Event", "Lock", "RLock", "Thread", "wait_for"]
