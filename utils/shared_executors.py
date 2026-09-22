"""Named, module-level thread pools, visible to diagnostics and shut down once.

Code that fans work out (quotes for a basket, history for a list of symbols)
has been creating a ``ThreadPoolExecutor`` per call. Each one starts its own
threads, and a burst of calls starts dozens at once: under the gthread worker
those are real OS threads on top of the request pool, and nothing reports how
many exist. :func:`get_executor` hands out one pool per name for the life of
the process instead, and :func:`executor_stats` shows each pool's size and
queue.

The first call for a name fixes its size; later calls with a different
``max_workers`` get the existing pool. Pools are shut down by
``utils.shutdown.shutdown_runtime`` and, as a backstop, at interpreter exit,
without waiting and with queued work cancelled.

Under eventlet a ``ThreadPoolExecutor``'s threads are green, exactly as the
per-call pools they replace were, so nothing changes there.
"""

from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from utils import real_threading
from utils.logging import get_logger

logger = get_logger(__name__)

# Real, with a critical section of dict work only (constructing an executor
# starts no threads), so any thread in any runtime may ask for a pool.
_lock = real_threading.Lock()
_executors: dict[str, ThreadPoolExecutor] = {}
_hooks_registered = False


def _register_shutdown() -> None:
    """Register the pool teardown with shutdown_runtime and atexit, once."""
    global _hooks_registered
    with _lock:
        if _hooks_registered:
            return
        _hooks_registered = True
    atexit.register(shutdown_all)
    try:
        from utils.shutdown import register_shutdown_hook

        register_shutdown_hook(shutdown_all, name="shared-executors", budget_s=5.0)
    except Exception:
        logger.exception("Could not register the shared thread pools for shutdown")


def get_executor(name: str, max_workers: int) -> ThreadPoolExecutor:
    """Return the process-wide pool called ``name``, creating it on first use.

    Args:
        name: A stable name for the pool (``"quotes"``, ``"history"``). It is
            also the thread name prefix.
        max_workers: The pool size. Fixed by the first call for ``name``.

    Returns:
        The shared ``ThreadPoolExecutor``.
    """
    executor = _executors.get(name)
    if executor is not None:
        return executor
    created = False
    with _lock:
        executor = _executors.get(name)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix=f"openalgo-{name}"
            )
            _executors[name] = executor
            created = True
    if created:
        _register_shutdown()
    return executor


def executor_stats() -> dict[str, dict[str, Any]]:
    """Size, live threads and queued work items for every shared pool."""
    with _lock:
        pools = dict(_executors)
    stats: dict[str, dict[str, Any]] = {}
    for name, executor in pools.items():
        entry: dict[str, Any] = {"max_workers": None, "threads": None, "queued": None}
        try:
            entry["max_workers"] = executor._max_workers
        except Exception:
            pass
        try:
            entry["threads"] = len(executor._threads)
        except Exception:
            pass
        try:
            entry["queued"] = executor._work_queue.qsize()
        except Exception:
            pass
        stats[name] = entry
    return stats


def shutdown_all() -> None:
    """Shut every pool down without waiting, cancelling work not yet started.

    Idempotent. A pool is removed from the registry as it is shut down, so a
    later ``get_executor`` for the same name builds a fresh one rather than
    handing out a pool that refuses work.
    """
    with _lock:
        pools = list(_executors.items())
        _executors.clear()
    for name, executor in pools:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logger.exception(f"Could not shut down the {name} thread pool")


__all__ = ["executor_stats", "get_executor", "shutdown_all"]
