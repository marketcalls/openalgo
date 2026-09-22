"""Which runtime this process is running under, answered without importing eventlet.

OpenAlgo runs under three runtimes and has to know which one it is in:

* ``gunicorn --worker-class eventlet -w 1``, the default production worker.
  eventlet monkey-patches the standard library before the app is imported, so
  ``threading.Lock``, ``time.sleep`` and friends are green.
* ``gunicorn --worker-class gthread -w 1``, opt-in per install through
  ``OPENALGO_WORKER_CLASS``. Nothing is patched and every request runs on a
  real OS thread from a fixed pool.
* ``uv run app.py``, the development server. Nothing is patched either.

**The question is whether eventlet patched this process, not whether it was
imported.** The test used to be ``"eventlet" in sys.modules``, which answers the
second. Under gthread eventlet stays installed as the fallback, and several
modules imported it merely to ask (``eventlet.patcher.is_monkey_patched``), so
the first such probe flipped every later ``in sys.modules`` guard into its
eventlet branch in a process nothing had patched. Worse, those branches called
``eventlet.patcher.original("threading")``, which on an unpatched interpreter
builds a second copy of the threading module whose threads are invisible to
``threading.enumerate()``.

So :func:`is_monkey_patched` looks ``eventlet.patcher`` up in ``sys.modules``
and never imports it. If eventlet patched the process it is necessarily already
there (``monkey_patch`` lives in that module), and if it is absent nothing can
have patched anything. Patching cannot be undone, so a True answer is cached.

This module imports nothing from the project, because ``utils.real_threading``
and ``utils.logging`` import it. Keep it that way.
"""

from __future__ import annotations

import importlib
import os
import sys
import weakref
from types import ModuleType
from typing import Any

#: The key eventlet records a patch under, for each stdlib module a caller may
#: ask :func:`original` for. A name not listed is its own key.
_PATCH_KEY = {
    "threading": "thread",
    "_thread": "thread",
    "thread": "thread",
    "queue": "thread",
    "time": "time",
    "socket": "socket",
    "ssl": "socket",
    "select": "select",
    "selectors": "select",
    "os": "os",
    "subprocess": "subprocess",
}

#: Patch keys already seen patched. A set add is atomic under the GIL, and an
#: entry is never removed because eventlet cannot unpatch.
_patched: set[str] = set()

#: Gunicorn module that defines each worker class, and the label reported for it.
_WORKER_MODULE_LABELS = {
    "gunicorn.workers.gthread": "gthread",
    "gunicorn.workers.geventlet": "eventlet",
    "gunicorn.workers.sync": "sync",
    "gunicorn.workers.ggevent": "gevent",
    "gunicorn.workers.gtornado": "tornado",
}

#: What the launcher's post_worker_init hook recorded about this worker, or
#: None when no hook registered one (dev server, or gunicorn started by hand).
_registered: dict[str, Any] | None = None
_worker_ref: weakref.ReferenceType | None = None


def is_monkey_patched(module: str = "thread") -> bool:
    """Return True when eventlet has monkey-patched ``module`` in this process.

    Never imports eventlet. ``module`` is an eventlet patch key: ``thread``
    (the default, covering ``threading``, ``_thread`` and ``queue``),
    ``socket``, ``time``, ``select``, ``os`` or ``subprocess``.

    Args:
        module: The eventlet patch key to ask about.

    Returns:
        True only when eventlet is loaded and reports that key as patched.
    """
    if module in _patched:
        return True
    patcher = sys.modules.get("eventlet.patcher")
    if patcher is None:
        return False
    try:
        patched = bool(patcher.is_monkey_patched(module))
    except Exception:
        return False
    if patched:
        _patched.add(module)
    return patched


def original(name: str) -> ModuleType:
    """Return the unpatched stdlib module ``name``.

    Under eventlet this is ``eventlet.patcher.original(name)``, reached through
    ``sys.modules`` rather than an import. Everywhere else the stdlib module is
    already the original, so it is returned as is. Unlike calling
    ``eventlet.patcher.original`` directly, this never builds a second copy of a
    module in a process nothing patched.

    Args:
        name: A stdlib module name such as ``"threading"``, ``"queue"`` or
            ``"time"``.

    Returns:
        The module whose functions are the real, blocking OS primitives.
    """
    if is_monkey_patched(_PATCH_KEY.get(name, name)):
        return sys.modules["eventlet.patcher"].original(name)
    return importlib.import_module(name)


def register_gunicorn_worker(worker: Any) -> None:
    """Record the running gunicorn worker. Called only by the launcher's hooks.

    The launcher's ``post_worker_init`` hook passes the worker object so the
    app can report the real worker class and thread budget instead of inferring
    them. Only attributes are read; nothing here can fail the worker.

    Args:
        worker: The gunicorn worker instance.
    """
    global _registered, _worker_ref

    cfg = getattr(worker, "cfg", None)
    label = _WORKER_MODULE_LABELS.get(type(worker).__module__)
    if label is None:
        raw = str(getattr(cfg, "worker_class_str", "") or type(worker).__name__)
        label = raw.rsplit(".", 1)[-1].lower() or "unknown"

    def _int_or_none(value: Any) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    info = {
        "worker_class": label,
        "threads": _int_or_none(getattr(cfg, "threads", None)),
        "workers": _int_or_none(getattr(cfg, "workers", None)),
        "graceful_timeout": _int_or_none(getattr(cfg, "graceful_timeout", None)),
        "pid": os.getpid(),
    }
    try:
        ref = weakref.ref(worker)
    except TypeError:
        ref = None
    _registered = info
    _worker_ref = ref


def registered_worker() -> dict[str, Any] | None:
    """Return a copy of what :func:`register_gunicorn_worker` recorded, or None."""
    info = _registered
    return dict(info) if info is not None else None


def under_gunicorn() -> bool:
    """Return True when this process is a gunicorn worker."""
    return _registered is not None or "gunicorn.workers.base" in sys.modules


def worker_class() -> str:
    """Name the worker this process serves requests on.

    Returns:
        ``"eventlet"`` or ``"gthread"`` for the two supported gunicorn workers,
        another gunicorn worker's name (``"sync"`` and so on) if one is used,
        or ``"dev"`` for the development server. The worker registered by the
        launcher wins; otherwise eventlet is recognised by its patching and
        gunicorn's other workers by the module gunicorn loaded for them.
    """
    info = _registered
    if info is not None:
        return info["worker_class"]
    if is_monkey_patched("thread"):
        return "eventlet"
    if "gunicorn.workers.base" not in sys.modules:
        return "dev"
    for module_name, label in _WORKER_MODULE_LABELS.items():
        if label != "eventlet" and module_name in sys.modules:
            return label
    return "sync"


def gthread_active() -> bool:
    """Return True when requests are served by gunicorn's gthread worker.

    Anything a trader could notice (refusing a request, capping streams,
    bounding a broker queue wait) is enforced only when this is True, so the
    eventlet worker and the development server behave exactly as before.
    """
    return worker_class() == "gthread"


def configured_threads() -> int | None:
    """Return the gthread worker's thread count, or None when there is none.

    Read from the registered worker's configuration, then from
    ``OPENALGO_EFFECTIVE_THREADS`` (exported by the launcher, not a setting in
    ``.env``). Under eventlet and on the development server there is no thread
    budget, so this is None; it never invents a number.
    """
    if worker_class() != "gthread":
        return None
    info = _registered
    if info is not None and info.get("threads"):
        return info["threads"]
    raw = os.environ.get("OPENALGO_EFFECTIVE_THREADS", "").strip().strip("'\"")
    try:
        threads = int(raw)
    except ValueError:
        return None
    return threads if threads > 0 else None


def requested_worker_class() -> str:
    """Return the worker ``OPENALGO_WORKER_CLASS`` asks for: eventlet or gthread.

    This is what the operator asked for, which can differ from
    :func:`worker_class` until the service is restarted through the launcher.
    Anything other than ``gthread`` means the default, eventlet.
    """
    raw = os.environ.get("OPENALGO_WORKER_CLASS", "").strip().strip("'\"").lower()
    return "gthread" if raw == "gthread" else "eventlet"


def launcher_info() -> dict[str, Any] | None:
    """Return what the launcher exported about this start, or None without it.

    The launcher exports these as process variables for this report. They are
    not configuration and are never read from ``.env``.
    """
    version = os.environ.get("OPENALGO_LAUNCHER_VERSION")
    if not version:
        return None
    threads = os.environ.get("OPENALGO_EFFECTIVE_THREADS")
    try:
        threads_value: int | None = int(threads) if threads else None
    except ValueError:
        threads_value = None
    return {
        "version": version,
        "requested": os.environ.get("OPENALGO_REQUESTED_WORKER_CLASS"),
        "effective": os.environ.get("OPENALGO_EFFECTIVE_WORKER_CLASS"),
        "threads": threads_value,
    }


def gthread_pool_stats() -> dict[str, int | None] | None:
    """Return a best-effort view of the gthread worker's request pool.

    Reads private attributes of gunicorn's ThreadWorker, each in its own
    try/except, so a gunicorn release that renames one costs that figure and
    nothing else.

    Returns:
        ``{"spawned", "busy", "waiting", "open_connections"}`` under a
        registered gthread worker, otherwise None.
    """
    if worker_class() != "gthread" or _worker_ref is None:
        return None
    worker = _worker_ref()
    if worker is None:
        return None
    stats: dict[str, int | None] = {
        "spawned": None,
        "busy": None,
        "waiting": None,
        "open_connections": None,
    }
    pool = getattr(worker, "tpool", None)
    try:
        stats["spawned"] = len(pool._threads)
    except Exception:
        pass
    try:
        stats["busy"] = len(worker.futures)
    except Exception:
        pass
    try:
        stats["waiting"] = pool._work_queue.qsize()
    except Exception:
        pass
    try:
        stats["open_connections"] = int(worker.nr_conns)
    except Exception:
        pass
    return stats


__all__ = [
    "configured_threads",
    "gthread_active",
    "gthread_pool_stats",
    "is_monkey_patched",
    "launcher_info",
    "original",
    "register_gunicorn_worker",
    "registered_worker",
    "requested_worker_class",
    "under_gunicorn",
    "worker_class",
]
