# utils/db_sessions.py
"""Central registry of scoped sessions and a single place to release them.

Every ``scoped_session`` holds a DB connection per thread (per green thread
under eventlet) until ``.remove()`` is called. Production is one Gunicorn
worker that never restarts, so a session left behind on any code path
accumulates until the process hits its descriptor limit.

Flask requests are covered by ``teardown_appcontext`` in ``app.py``. Work that
runs *outside* a request - background threads, schedulers, event-bus callbacks -
has no app context and no teardown, so it must call
``remove_all_scoped_sessions()`` itself when it finishes.
"""

import sys

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
    ("database.strategy_db", "db_session"),
    ("database.user_db", "db_session"),
    ("database.action_center_db", "db_session"),
    ("database.qty_freeze_db", "db_session"),
    ("database.sandbox_db", "db_session"),
    ("database.analyzer_db", "db_session"),
    ("database.chart_prefs_db", "db_session"),
    ("database.chartink_db", "db_session"),
    ("database.flow_db", "db_session"),
    ("database.scalping_db", "db_session"),
    ("database.leverage_db", "db_session"),
    ("database.strategy_portfolio_db", "db_session"),
    ("database.market_calendar_db", "db_session"),
    ("database.telegram_db", "db_session"),
    ("database.symbol", "db_session"),
    ("database.strategy_book_db", "db_session"),
    ("database.oauth_db", "db_session"),
    ("database.whatsapp_db", "db_session"),
]


def remove_all_scoped_sessions() -> None:
    """Release every scoped session bound to the calling thread.

    Never raises: this runs in ``finally`` blocks and on teardown paths where an
    error must not mask the original outcome.
    """
    for module_name, session_attr in SCOPED_SESSION_MODULES:
        # sys.modules, not import_module: a module that was never imported has
        # no session bound to this thread, and importing it here just to clean
        # it would create the engine it was avoiding.
        mod = sys.modules.get(module_name)
        if mod is None:
            continue
        session = getattr(mod, session_attr, None)
        if session is None:
            continue
        try:
            session.remove()
        except Exception:
            # Swallowed so one bad session cannot strand the rest, but logged:
            # a silent failure here is exactly how a descriptor leak hides.
            logger.exception(f"Could not release scoped session {module_name}.{session_attr}")
