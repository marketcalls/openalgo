"""Run LiteLLM's sync-to-async hops on a real OS thread under eventlet (#2081).

LiteLLM's synchronous code reaches async code through
``litellm.litellm_core_utils.asyncify.run_async_function``: it starts a new
event loop in the calling thread, or, when a loop is already running there,
in a ``ThreadPoolExecutor`` worker. The Responses-API bridge does this once
per streamed chunk, and it is the bridge every GPT-5.4 or newer model goes
through as soon as a reasoning effort is set.

Under eventlet that executor worker is a greenlet on the same OS thread, and
asyncio records the running loop per OS thread. LiteLLM's streaming logger
runs ``asyncio.run`` on its own executor, so while one of its loops is part
way through, the next chunk's hop finds "another loop running" and the whole
answer fails with ``Cannot run the event loop while another loop is running``.
It depends on timing, which is why the failure came and went.

The replacement keeps LiteLLM's contract (run the coroutine to completion and
return its result or raise its exception) but runs every coroutine on one
long-lived event loop owned by a real OS thread, so no other loop can share
its thread. A real thread waits natively, which costs a streamed chunk no
added latency; a greenlet on the hub polls instead, so it never freezes the
hub. Installed only when eventlet has patched the process: under gthread and
on the development server LiteLLM's executor is a real thread already, and
its own behaviour is left exactly as it was.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from utils import real_threading
from utils.logging import get_logger
from utils.runtime import is_monkey_patched, original

logger = get_logger(__name__)

#: Longest one hop may take. LiteLLM's own helper has no limit; this one only
#: guards against a hop that never finishes holding a turn forever.
HOP_TIMEOUT_S = 600.0
#: How often a greenlet on the hub checks for the result. Only the hub polls;
#: the agent's run thread is a real thread and waits natively.
HUB_POLL_S = 0.005

_lock = real_threading.Lock()
_worker: tuple[Any, asyncio.AbstractEventLoop] | None = None
_installed = False


def _start_worker() -> tuple[Any, asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = real_threading.Thread(target=run, name="litellm-async", daemon=True)
    thread.start()
    return thread, loop


def _worker_loop() -> tuple[Any, asyncio.AbstractEventLoop]:
    """The worker thread and its loop, started on first use and if it ever died."""
    global _worker
    with _lock:
        if _worker is None or not _worker[0].is_alive():
            _worker = _start_worker()
        return _worker


def _in_fresh_thread(async_function, args, kwargs):
    """Run on a new real thread with its own loop, for a hop made from the worker itself."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = asyncio.run(async_function(*args, **kwargs))
        except BaseException as exc:
            box["error"] = exc

    thread = real_threading.Thread(target=run, name="litellm-async-nested", daemon=True)
    thread.start()
    real_threading.join(thread)
    if "error" in box:
        raise box["error"]
    return box.get("result")


def run_async_function(async_function, *args, **kwargs):
    """Drop-in for LiteLLM's helper: the coroutine's result, or its exception."""
    thread, loop = _worker_loop()
    if real_threading.get_ident() == thread.ident:
        # A coroutine on the worker asked for another hop; waiting for the
        # worker from the worker would never finish.
        return _in_fresh_thread(async_function, args, kwargs)

    done = real_threading.Event()
    box: dict[str, Any] = {}

    def start() -> None:
        try:
            task = loop.create_task(async_function(*args, **kwargs))
        except BaseException as exc:
            box["error"] = exc
            done.set()
            return

        def finish(task: asyncio.Task) -> None:
            if task.cancelled():
                box["error"] = asyncio.CancelledError()
            elif task.exception() is not None:
                box["error"] = task.exception()
            else:
                box["result"] = task.result()
            done.set()

        task.add_done_callback(finish)

    loop.call_soon_threadsafe(start)
    if real_threading.on_hub_thread() or _on_main_thread():
        finished = real_threading.wait_for(done, HOP_TIMEOUT_S, poll=HUB_POLL_S)
    else:
        finished = done.wait(HOP_TIMEOUT_S)
    if not finished:
        raise TimeoutError("The model provider did not answer in time")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _on_main_thread() -> bool:
    """The hub runs on the main OS thread; a caller there must never block natively."""
    return real_threading.get_ident() == original("threading").main_thread().ident


def install() -> bool:
    """Route LiteLLM's sync-to-async helper through the real worker thread.

    Idempotent. Does nothing unless eventlet has patched threading. Replaces
    the helper on its own module, so modules imported later pick it up, and on
    every LiteLLM module already holding the original. Never raises: if
    LiteLLM's layout changes, the original helper stays in place.

    Returns:
        True when the replacement is in place.
    """
    global _installed
    if _installed:
        return True
    if not is_monkey_patched("thread"):
        return False
    try:
        from litellm.litellm_core_utils import asyncify

        original = asyncify.run_async_function
        asyncify.run_async_function = run_async_function
        for name, module in list(sys.modules.items()):
            if (
                name.startswith("litellm")
                and getattr(module, "run_async_function", None) is original
            ):
                module.run_async_function = run_async_function
        _installed = True
    except Exception:
        logger.exception("Could not route LiteLLM's async calls onto a real thread")
    return _installed
