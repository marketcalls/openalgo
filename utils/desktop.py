"""Desktop mode: running the dev server with no terminal attached.

The Windows desktop install (Phase 3, ``docs/plans/2026-11-05-desktop-panel-and-reset-plan.md``)
starts ``app.py`` from a keeper process that has no console. Three things that
are harmless in a terminal kill or hang the server there:

- Flask-SocketIO refuses to start the Werkzeug server when stdin is not a TTY
  ("The Werkzeug web server is not designed to run in production") unless it is
  passed ``allow_unsafe_werkzeug=True``. That is the crash that wrapping
  ``python app.py`` produces. The threading Werkzeug server is the right server
  for one user on one PC: gunicorn does not run on Windows.
- ``utils.env_check`` asks "Continue anyway? (y/N)" when ``.env`` is older than
  ``.sample.env``. With no terminal ``input()`` raises ``EOFError``, which counts
  as no, so the app exits before it serves anything.
- The debug reloader starts a second process the keeper does not know about.

And one thing is missing: a way to stop cleanly. A console sends Ctrl+C; a
keeper with no console cannot. So the keeper writes a stop file, and a watcher
here turns it into the same SIGINT that Ctrl+C delivers, so the one teardown
path in ``utils.shutdown`` stays the only one.

Enabled by ``FASTALGO_DESKTOP=1`` in the process environment, which the keeper
sets. ``.env`` is loaded with ``override=True``, so a flag there would also work,
but the keeper never writes one. Production (gunicorn) never runs the
``__main__`` block this is used from.
"""

import os
import signal
import threading
import time

_TRUE = ("1", "true", "t", "yes")

#: Seconds between checks for the stop file. A stop is a human action, so a
#: second of latency is invisible, and the check is one ``stat`` call.
STOP_POLL_S = 1.0


def is_desktop() -> bool:
    """True when the server was started by the desktop keeper."""
    return os.getenv("FASTALGO_DESKTOP", "").strip().lower() in _TRUE


def stop_file_path() -> str | None:
    """The file whose appearance asks the server to stop, or None if unset."""
    path = os.getenv("FASTALGO_STOP_FILE", "").strip()
    return path or None


def _watch(path: str, poll_s: float) -> None:
    while not os.path.exists(path):
        time.sleep(poll_s)
    # Imported here, not at module scope: utils.env_check imports this module
    # before logging is set up, and utils.logging costs seconds to import.
    from utils.logging import get_logger

    get_logger(__name__).info("Stop requested by the FastAlgo panel, shutting down")
    try:
        os.remove(path)
    except OSError:
        # The keeper removes it too; a stale file would only stop the next
        # start immediately, and the keeper clears it before every start.
        pass
    # Delivered to the main thread's handler, installed by
    # utils.shutdown.install_signal_handlers, exactly as Ctrl+C is.
    signal.raise_signal(signal.SIGINT)


def start_stop_watcher(poll_s: float = STOP_POLL_S) -> threading.Thread | None:
    """Start the stop-file watcher if desktop mode named a stop file.

    A daemon thread, so it never holds the process open. One per process: the
    only caller is the ``__main__`` block of ``app.py``, which runs once.
    """
    path = stop_file_path()
    if not is_desktop() or path is None:
        return None
    thread = threading.Thread(
        target=_watch, args=(path, poll_s), name="desktop-stop-watcher", daemon=True
    )
    thread.start()
    return thread
