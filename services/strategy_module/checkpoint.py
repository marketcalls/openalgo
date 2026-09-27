"""Periodic durability for live strategy runs.

``state`` holds a run in a plain in-process dict, which is the right home for
it while the worker is alive and no home at all once it dies. This module is
the bridge: every ``STRATEGY_CHECKPOINT_INTERVAL_SEC`` it writes one
``sm_strategy_checkpoint`` row per live run, so a crash costs at most the
seconds since the last pass rather than the whole run. ``recovery`` reads those
rows back on the next boot.

Three things about it are deliberate.

**Nothing starts at import time.** The loop begins only when a caller invokes
:func:`start`, and ends on :func:`stop`. Two modules in this codebase start a
scheduler as an import side effect, which means any tool that merely imports
the app - a migration, a one-off script, a test collection pass - spins up live
background work against the operator's database. Importing this module does
nothing at all.

**The loop is green.** It is a plain ``threading.Thread``, which eventlet
monkey-patches into a green thread, and that is what it must be: every pass
touches the run locks in ``state`` and writes through SQLAlchemy, both of which
belong to the hub. It takes a run's lock only to build the snapshot, which is
in-memory work, and writes the row after releasing it (see CLAUDE.md, "Nothing
may block or be blocked across the eventlet boundary").

**It prunes.** A row per run every few seconds for a trading day is thousands
of rows per run, in a Gunicorn worker that never restarts. Pruning runs on a
slow cycle rather than on every pass, because deleting is far more expensive
than appending and the table only has to stay bounded, not minimal.
"""

from __future__ import annotations

import atexit
import os
import threading
import time

from database import strategy_module_db as store
from services.strategy_module import state
from utils.db_sessions import remove_all_scoped_sessions
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "CHECKPOINT_INTERVAL_SEC",
    "CHECKPOINT_KEEP",
    "PRUNE_EVERY_PASSES",
    "is_running",
    "start",
    "stop",
    "write_once",
]


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        logger.warning("%s is not a number; using %s", name, default)
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    try:
        value = int(float(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        logger.warning("%s is not a number; using %s", name, default)
        return default
    return value if value > 0 else default


#: How often a snapshot is written for every live run.
CHECKPOINT_INTERVAL_SEC = _env_float("STRATEGY_CHECKPOINT_INTERVAL_SEC", 5.0)

#: Rows kept per run when a prune runs. Recovery reads exactly one row, the
#: newest, so the rest exist only for the P&L chart, which does not need
#: second-level resolution over a whole session.
CHECKPOINT_KEEP = _env_int("STRATEGY_CHECKPOINT_KEEP", 200)

#: Passes between prunes. Pruning on every pass would run a delete per run
#: every few seconds to reclaim one row; on this cycle the table settles at
#: roughly ``CHECKPOINT_KEEP + PRUNE_EVERY_PASSES`` rows per run, which is
#: bounded, and that is the whole requirement. Recovery is unaffected whatever
#: the cycle: it reads ``latest_checkpoint``, and the newest row is the one row
#: a prune can never remove.
PRUNE_EVERY_PASSES = _env_int("STRATEGY_CHECKPOINT_PRUNE_EVERY_PASSES", 120)

#: Longest the loop sleeps before re-checking the stop flag, so stop() is
#: prompt rather than waiting out a whole interval.
_STOP_CHECK_SEC = 0.1


# One shared writer for the whole worker. A thread per run would leak a thread
# per run in a process that never restarts, and there is nothing per run to
# hold: the pass reads whatever ``state`` currently has.
_thread: threading.Thread | None = None
_running = False
_lifecycle_lock = threading.Lock()
_passes_since_prune = 0


def write_once(*, prune: bool | None = None) -> int:
    """Write one checkpoint per live run. Returns how many rows were written.

    This is the whole of a pass, factored out so it can be driven directly
    rather than by waiting on the loop.

    Args:
        prune: Force pruning on (True) or off (False) for this pass. Left
            unset, the pass prunes on its own cycle, every
            ``PRUNE_EVERY_PASSES`` calls.

    Returns:
        The number of checkpoint rows written.
    """
    global _passes_since_prune

    if prune is None:
        _passes_since_prune += 1
        prune = _passes_since_prune >= PRUNE_EVERY_PASSES
    if prune:
        _passes_since_prune = 0

    written = 0
    try:
        for run_id in state.active_run_ids():
            try:
                # Under the lock: in-memory only. snapshot_for_checkpoint deep
                # copies the legs, so what comes out is safe to write from
                # outside, and the database work happens after the release.
                with state.run_state(run_id) as run:
                    if run is None:
                        # Finished between active_run_ids() and here. Normal.
                        continue
                    snapshot = state.snapshot_for_checkpoint(run)

                if store.write_checkpoint(run_id, snapshot):
                    written += 1
                if prune:
                    store.prune_checkpoints(run_id, CHECKPOINT_KEEP)
            except Exception:
                # One run's failure must not cost the others their durability,
                # and must never end the loop: a writer that died on a single
                # bad run would leave every run unrecoverable from then on.
                logger.exception("Could not checkpoint run %s", run_id)
    finally:
        # The loop runs outside any Flask app context, so teardown_appcontext
        # never fires and every session this pass bound would stay bound to the
        # thread for the life of the worker. Same reason as the scheduler jobs
        # in services/flow_scheduler_service.py.
        remove_all_scoped_sessions()

    return written


def _run_loop() -> None:
    """Write a pass, sleep, repeat, until stop() is called."""
    logger.info(
        "Strategy checkpoint writer started (every %ss, keeping %s rows per run)",
        CHECKPOINT_INTERVAL_SEC,
        CHECKPOINT_KEEP,
    )
    while _running:
        try:
            write_once()
        except Exception:
            # write_once already guards each run; this is the last resort so a
            # failure in the pass scaffolding itself cannot end the loop.
            logger.exception("Strategy checkpoint pass failed")
        _sleep(CHECKPOINT_INTERVAL_SEC)
    logger.info("Strategy checkpoint writer stopped")


def _sleep(seconds: float) -> None:
    """Sleep in slices, so stop() does not wait out a whole interval."""
    remaining = seconds
    while _running and remaining > 0:
        slice_ = min(_STOP_CHECK_SEC, remaining)
        time.sleep(slice_)
        remaining -= slice_


def start() -> bool:
    """Start the shared writer. Returns whether this call started it.

    Idempotent: a second call while it is running is a no-op, so a caller does
    not have to know whether somebody else has already started it.
    """
    global _thread, _running
    with _lifecycle_lock:
        if _running:
            return False
        _running = True
        # Plain threading.Thread, so this is GREEN under eventlet. It must be:
        # it takes the run locks in state and writes through SQLAlchemy, and
        # both of those belong to the hub.
        _thread = threading.Thread(target=_run_loop, name="strategy-checkpoint", daemon=True)
        _thread.start()
        atexit.register(stop)
        return True


def stop() -> None:
    """Stop the writer and release its thread. Idempotent."""
    global _thread, _running
    with _lifecycle_lock:
        if not _running and _thread is None:
            return
        _running = False
        thread = _thread
        _thread = None

    if thread is not None and thread is not threading.current_thread():
        # Green under eventlet, so this join yields; the timeout is for the dev
        # server, where it is a real thread.
        thread.join(timeout=5)

    try:
        atexit.unregister(stop)
    except Exception:
        logger.exception("Could not unregister the checkpoint writer atexit hook")


def is_running() -> bool:
    """Whether the shared writer is currently running."""
    return _running
