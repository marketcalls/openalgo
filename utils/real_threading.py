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

Where eventlet has not patched the process (the gthread worker and the dev
server) these are simply the stdlib primitives. Whether it has is answered by
``utils.runtime.is_monkey_patched``, which inspects patch state and never
imports eventlet: importing it merely to ask used to flip this choice in a
process nothing had patched.

**Calling into the green world from a real thread.** A real OS thread (the
agent, the Telegram bot) that needs service code guarded by green primitives
must not call it directly under eventlet. :func:`run_on_hub` and
:func:`submit_to_hub` hand the call to a green thread started once at app
startup by :func:`start_hub_worker`. Everywhere else, and when called from the
hub itself, they simply call the function.
"""

import queue
import sys
import threading
import time

from utils import runtime as _runtime
from utils.runtime import is_monkey_patched

if is_monkey_patched("thread"):
    _threading = _runtime.original("threading")
    _queue = _runtime.original("queue")
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
Full = _queue.Full

#: The real OS thread id, whatever eventlet has done to ``threading.get_ident``
#: (under eventlet the patched one returns a greenlet id).
_real_get_ident = _threading.get_ident

#: The unpatched ``time.sleep``: it blocks the calling OS thread. Only for real
#: threads; a greenlet calling it stops the hub for the whole sleep.
sleep = _runtime.original("time").sleep


def wait_for(event, timeout, poll=0.02):
    """Wait for an Event another OS thread will set, without freezing the hub.

    Neither primitive is usable directly for a wait of any length under
    eventlet:

    * a green Event never wakes on a ``set()`` from a real OS thread, so the
      waiter sits out its entire timeout and reports failure for something that
      arrived on time;
    * a real Event wakes correctly, but ``Event.wait()`` blocks, and a greenlet
      blocking stops the hub -- every other request on this worker -- for the
      whole wait.

    Polling a real Event keeps both properties. ``is_set()`` only reads a flag,
    and the sleep between checks is eventlet's, so the greenlet yields.

    Where nothing is patched the caller is a real thread and the native wait is
    both correct and prompt, so it is used directly.

    Pass a real Event (``Event`` from this module). Returns True if it was set
    before the timeout, matching ``Event.wait``.
    """
    if not is_monkey_patched("thread"):
        return event.wait(timeout)
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
    Where nothing is patched the native join is used.

    Returns True if the thread finished, False if the timeout ran out, so a
    caller can tell the difference the way ``is_alive()`` after ``join()`` does.
    """
    if not is_monkey_patched("thread"):
        thread.join(timeout)
        return not thread.is_alive()
    deadline = None if timeout is None else time.monotonic() + timeout
    while thread.is_alive():
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(poll)
    return True


# ---------------------------------------------------------------------------
# Marshalling a call from a real OS thread onto the eventlet hub
# ---------------------------------------------------------------------------

#: Most calls a real thread may have waiting for the hub at once. Past this a
#: call is refused rather than queued without bound in a worker that never
#: restarts.
HUB_QUEUE_MAX = 10000

#: Bytes read from the wakeup socket per recv() when the drainer wakes.
_WAKE_READ_BYTES = 4096

_hub_queue = Queue(maxsize=HUB_QUEUE_MAX)
_hub_state_lock = Lock()
_hub_thread_ident = None
_hub_worker = None
#: A plain flag rather than ``_hub_worker.is_alive()``: the drainer is a green
#: thread, and a real thread should not reach into its internals to ask.
_hub_running = False
_hub_missing_warned = False
#: The drainer's wakeup: a pair of real, non-blocking sockets, created once by
#: start_hub_worker and kept for the life of the process. A real thread that
#: queues a call writes one byte to the write end; the drainer waits for the
#: read end to become readable, a wait the hub serves like any socket read. So
#: an idle drainer costs the hub nothing, where polling the queue on a timer
#: woke the single worker's hub fifty times a second for the life of the worker.
_hub_wake_reader = None
_hub_wake_writer = None
_hub_wake_failed_logged = False


class HubQueueFull(RuntimeError):
    """Raised when the hub already has ``HUB_QUEUE_MAX`` calls waiting."""


def _log():
    """The module logger, imported late: utils.logging imports this module."""
    from utils.logging import get_logger

    return get_logger(__name__)


def hub_worker_running() -> bool:
    """Return True when the green drainer started by start_hub_worker is running."""
    return _hub_running


def on_hub_thread() -> bool:
    """Return True when the caller may use green primitives directly.

    True wherever nothing is patched, and under eventlet on the hub's own OS
    thread. False only for a real OS thread under eventlet.
    """
    if not is_monkey_patched("thread"):
        return True
    ident = _hub_thread_ident
    return ident is not None and _real_get_ident() == ident


def _needs_marshal() -> bool:
    """True when this call must be handed to the hub rather than made inline.

    When eventlet patched the process but no drainer was started, there is no
    way to reach the hub, so the call is made inline as it always was, and
    that is logged once so the missing startup call is visible.
    """
    global _hub_missing_warned

    if not is_monkey_patched("thread"):
        return False
    if not hub_worker_running():
        if not _hub_missing_warned:
            _hub_missing_warned = True
            _log().warning(
                "A background thread asked to run work on the web server's "
                "main loop before that loop was ready, so it ran directly. "
                "start_hub_worker() was not called at startup."
            )
        return False
    return not on_hub_thread()


def _new_wake_pair():
    """Return a connected pair of real, non-blocking sockets for waking the drainer.

    Real (unpatched) sockets, so a real thread's send() is a plain system call
    that never reaches the hub, and the drainer's recv() never trampolines.
    """
    reader, writer = _runtime.original("socket").socketpair()
    reader.setblocking(False)
    writer.setblocking(False)
    return reader, writer


def _wait_readable(sock) -> None:
    """Park the calling green thread until ``sock`` is readable.

    eventlet's own wait-for-descriptor, found in ``sys.modules`` the way
    ``utils.runtime.original`` finds the patcher: this runs only under eventlet,
    where ``eventlet.hubs`` is necessarily loaded, and importing eventlet here
    would put it into processes that never use it.
    """
    sys.modules["eventlet.hubs"].trampoline(sock.fileno(), read=True)


def _consume_wakeups(reader) -> bool:
    """Read every pending wakeup byte. False when the other end has closed."""
    while True:
        try:
            data = reader.recv(_WAKE_READ_BYTES)
        except (BlockingIOError, InterruptedError):
            return True
        if not data:
            return False
        if len(data) < _WAKE_READ_BYTES:
            return True


def _wake_hub() -> None:
    """Wake the drainer after queueing a call. Safe from any thread.

    A full socket buffer means wakeups are already pending, so that is not an
    error. Any other failure is logged once: the call stays queued, and its
    caller's own timeout reports it.
    """
    global _hub_wake_failed_logged

    writer = _hub_wake_writer
    if writer is None:
        return
    try:
        writer.send(b"\0")
    except (BlockingIOError, InterruptedError):
        pass
    except OSError:
        if not _hub_wake_failed_logged:
            _hub_wake_failed_logged = True
            _log().exception("Could not wake the web server's main loop for a background call")


def _drain_hub_queue() -> None:
    """Run queued calls on the hub. A green thread under eventlet.

    The queue is real, so a blocking get() from a green thread would freeze
    the worker. The drainer instead sleeps until a real thread's wakeup byte
    makes the wakeup socket readable, then reads the queue with get_nowait()
    until it is empty. The bytes are read before the queue, so a call queued
    while the queue is being emptied leaves its byte behind and wakes the next
    wait at once: no call is left waiting for a wakeup that already happened.

    Each call runs on a green thread of its own, so one that waits (an order
    placed for the agent, a strategy stopped for the Telegram bot) never holds
    up the calls queued behind it. Calls start in the order they were queued.
    Each call's own wrapper catches its exceptions, so the loop only guards
    against a defect in that wrapper.
    """
    global _hub_running

    reader = _hub_wake_reader
    try:
        while True:
            _wait_readable(reader)
            if not _consume_wakeups(reader):
                _log().error(
                    "The web server's main loop stopped taking calls from background threads"
                )
                return
            while True:
                try:
                    task = _hub_queue.get_nowait()
                except Empty:
                    break
                try:
                    # The patched threading.Thread: a green thread on this hub.
                    threading.Thread(target=task, name="openalgo-hub-call", daemon=True).start()
                except Exception:
                    _log().exception("A call handed to the web server's main loop could not start")
    except Exception:
        _log().exception("The web server's main loop stopped taking calls from background threads")
    finally:
        _hub_running = False


def start_hub_worker() -> bool:
    """Start the green drainer that runs calls handed over by real threads.

    Idempotent. A no-op returning False unless eventlet has patched the
    process. Must be called from the hub's own thread (app startup), because
    that is the thread whose id marks "already on the hub" and the green
    drainer belongs to the hub that starts it.

    Returns:
        True when the drainer is running after the call.
    """
    global _hub_thread_ident, _hub_worker, _hub_running, _hub_wake_reader, _hub_wake_writer

    if not is_monkey_patched("thread"):
        return False
    with _hub_state_lock:
        if _hub_running:
            return True
        if _hub_wake_reader is None:
            # Once per process, before the flag below lets real threads queue.
            _hub_wake_reader, _hub_wake_writer = _new_wake_pair()
        _hub_thread_ident = _real_get_ident()
        # threading.Thread is the patched one here, so this is a green thread.
        worker = threading.Thread(target=_drain_hub_queue, name="openalgo-hub-worker", daemon=True)
        _hub_worker = worker
        # Set before start(): a call queued before the drainer's first wait
        # leaves its wakeup byte behind, so that wait returns at once and the
        # call is picked up, instead of running inline meanwhile.
        _hub_running = True
    try:
        worker.start()
    except BaseException:
        _hub_running = False
        raise
    return True


def run_on_hub(fn, *args, timeout, **kwargs):
    """Call ``fn(*args, **kwargs)`` in the green world and return its result.

    Under eventlet, from a real OS thread, the call is queued for the hub
    worker and the caller waits on a real Event with a plain blocking wait,
    which is correct because the caller is real. Anywhere else (the hub
    itself, the gthread worker, the dev server) ``fn`` is simply called.

    ``timeout`` is keyword-only and is consumed here, so ``fn`` cannot receive
    a keyword argument of that name through this helper.

    Args:
        fn: The callable to run.
        *args: Positional arguments for ``fn``.
        timeout: Seconds to wait for the result.
        **kwargs: Keyword arguments for ``fn``.

    Returns:
        Whatever ``fn`` returned.

    Raises:
        TimeoutError: The call did not finish in time. If it had not started
            it never will; if it had, it may still complete on the hub.
        HubQueueFull: Too many calls are already waiting for the hub.
        Exception: Whatever ``fn`` raised, re-raised in the caller.
    """
    if not _needs_marshal():
        return fn(*args, **kwargs)

    done = Event()
    state_lock = Lock()
    box = {"state": "queued"}

    def task():
        with state_lock:
            if box["state"] == "abandoned":
                return
            box["state"] = "running"
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            box["error"] = exc
        finally:
            done.set()

    try:
        _hub_queue.put_nowait(task)
    except Full:
        raise HubQueueFull(
            "The web server's main loop is too busy to take this call right now."
        ) from None
    _wake_hub()

    if not done.wait(timeout):
        with state_lock:
            if box["state"] == "queued":
                box["state"] = "abandoned"
        raise TimeoutError(f"the call did not finish on the hub within {timeout}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def submit_to_hub(fn, *args, **kwargs) -> None:
    """Fire-and-forget form of :func:`run_on_hub`.

    Under eventlet, from a real OS thread, ``fn`` is queued for the hub and
    this returns at once; an exception from ``fn`` is logged. Anywhere else
    ``fn`` is called inline and its exception propagates to the caller, as a
    direct call would.

    Raises:
        HubQueueFull: Too many calls are already waiting for the hub.
    """
    if not _needs_marshal():
        fn(*args, **kwargs)
        return

    def task():
        try:
            fn(*args, **kwargs)
        except Exception:
            name = getattr(fn, "__qualname__", repr(fn))
            _log().exception(f"Background call {name} failed on the web server's main loop")

    try:
        _hub_queue.put_nowait(task)
    except Full:
        raise HubQueueFull(
            "The web server's main loop is too busy to take this call right now."
        ) from None
    _wake_hub()


__all__ = [
    "Condition",
    "Empty",
    "Event",
    "Full",
    "HubQueueFull",
    "Lock",
    "Queue",
    "RLock",
    "Thread",
    "hub_worker_running",
    "is_monkey_patched",
    "join",
    "on_hub_thread",
    "run_on_hub",
    "sleep",
    "start_hub_worker",
    "submit_to_hub",
    "wait_for",
]
