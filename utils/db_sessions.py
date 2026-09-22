# utils/db_sessions.py
"""Central registry of scoped sessions and a single place to release them.

Every ``scoped_session`` holds a DB connection per thread (per green thread
under eventlet) until ``.remove()`` is called. Production is one Gunicorn
worker that never restarts, so a session left behind on any code path
accumulates until the process hits its descriptor limit.

Flask requests are covered by ``teardown_appcontext`` in ``app.py``. Work that
runs *outside* a request - background threads, schedulers, event-bus callbacks -
has no app context and no teardown, so it must call
``remove_all_scoped_sessions()`` itself when it finishes. The
:func:`releases_scoped_sessions` decorator and the :func:`session_cleanup`
context manager do that in a ``finally``.

**Broker master-contract sessions are swept too.** Each broker plugin's
``broker/<name>/database/master_contract_db.py`` defines its own
``db_session``, and some request code queries through it. Under eventlet every
request ran on a fresh greenlet, so its thread-local session was dropped with
it. Under the gthread worker request threads are pooled and never exit, so a
session nothing removes stays open on its thread from one request to the next,
holding a connection and an identity map whose rows can be a daily
re-download out of date. Those modules are found in ``sys.modules`` by name,
so a broker that was never loaded is never imported here.
"""

import functools
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from utils.logging import get_logger

logger = get_logger(__name__)

# (module path, attribute name) for every scoped_session in the project.
SCOPED_SESSION_MODULES = [
    ("database.auth_db", "db_session"),
    ("database.traffic_db", "logs_session"),
    ("database.apilog_db", "db_session"),
    ("database.latency_db", "latency_session"),
    ("database.health_db", "health_session"),
    ("database.settings_db", "db_session"),
    ("database.user_db", "db_session"),
    ("database.action_center_db", "db_session"),
    ("database.qty_freeze_db", "db_session"),
    ("database.sandbox_db", "db_session"),
    ("database.analyzer_db", "db_session"),
    ("database.chart_prefs_db", "db_session"),
    ("database.chartink_db", "db_session"),
    ("database.flow_db", "db_session"),
    ("database.scalping_db", "db_session"),
    ("database.watchlist_db", "db_session"),
    ("database.alert_log_db", "db_session"),
    ("database.leverage_db", "db_session"),
    ("database.strategy_portfolio_db", "db_session"),
    ("database.market_calendar_db", "db_session"),
    ("database.telegram_db", "db_session"),
    ("database.symbol", "db_session"),
    ("database.strategy_book_db", "db_session"),
    ("database.strategy_module_db", "db_session"),
    ("database.oauth_db", "db_session"),
    ("database.whatsapp_db", "db_session"),
    ("database.agent_db", "db_session"),
]


#: Modules registered at runtime by register_scoped_session().
_registered: list[tuple[str, str]] = []

#: Broker master-contract modules found in sys.modules, and the sys.modules
#: size they were found at. Scanning every module name on every request would
#: cost a few thousand string checks per teardown; importing only ever adds
#: modules, so the scan is repeated only when the count changes.
_broker_modules: tuple[str, ...] = ()
_broker_scan_size = -1

_BROKER_PREFIX = "broker."
_BROKER_SUFFIX = ".database.master_contract_db"


def register_scoped_session(module_name: str, attr: str = "db_session") -> None:
    """Add a module's scoped session to the set released after each unit of work.

    For a module outside this file's list. Idempotent.

    Args:
        module_name: Dotted module path, looked up in ``sys.modules`` when
            sessions are released (never imported).
        attr: The attribute holding the ``scoped_session``.
    """
    entry = (module_name, attr)
    if entry in SCOPED_SESSION_MODULES or entry in _registered:
        return
    _registered.append(entry)


def _broker_master_contract_modules() -> tuple[str, ...]:
    """Names of loaded ``broker.<name>.database.master_contract_db`` modules."""
    global _broker_modules, _broker_scan_size

    size = len(sys.modules)
    if size == _broker_scan_size:
        return _broker_modules
    found = tuple(
        name
        for name in list(sys.modules)
        if name.startswith(_BROKER_PREFIX)
        and name.endswith(_BROKER_SUFFIX)
        and name.count(".") == 3
    )
    _broker_modules = found
    _broker_scan_size = size
    return found


def _release(module_name: str, session_attr: str) -> None:
    # sys.modules, not import_module: a module that was never imported has
    # no session bound to this thread, and importing it here just to clean
    # it would create the engine it was avoiding.
    mod = sys.modules.get(module_name)
    if mod is None:
        return
    session = getattr(mod, session_attr, None)
    if session is None or not hasattr(session, "remove"):
        return
    try:
        session.remove()
    except Exception:
        # Swallowed so one bad session cannot strand the rest, but logged:
        # a silent failure here is exactly how a descriptor leak hides.
        logger.exception(f"Could not release scoped session {module_name}.{session_attr}")


def remove_all_scoped_sessions() -> None:
    """Release every scoped session bound to the calling thread.

    Covers the modules listed here, those added with
    :func:`register_scoped_session`, and every loaded broker master-contract
    module. Never raises: this runs in ``finally`` blocks and on teardown paths
    where an error must not mask the original outcome.
    """
    for module_name, session_attr in SCOPED_SESSION_MODULES:
        _release(module_name, session_attr)
    for module_name, session_attr in list(_registered):
        _release(module_name, session_attr)
    try:
        broker_modules = _broker_master_contract_modules()
    except Exception:
        logger.exception("Could not list broker master contract modules to release their sessions")
        return
    for module_name in broker_modules:
        _release(module_name, "db_session")


@contextmanager
def session_cleanup() -> Iterator[None]:
    """Release the calling thread's scoped sessions when the block ends.

    For a background loop iteration, an executor task or anything else that
    runs outside a Flask request and so never reaches ``teardown_appcontext``.
    """
    try:
        yield
    finally:
        remove_all_scoped_sessions()


def releases_scoped_sessions[F: Callable](fn: F) -> F:
    """Decorate a scheduler job, bus handler or task to release sessions after it.

    The sessions are released in a ``finally``, so a job that raises still
    gives its connections back.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            remove_all_scoped_sessions()

    return wrapper  # type: ignore[return-value]
