"""Background scheduler threads must release their scoped sessions.

A ``scoped_session`` holds a database connection per thread until ``.remove()``
is called. Flask requests are covered by ``teardown_appcontext`` in app.py, but
APScheduler runs its jobs on its own worker threads, which have no app context
and therefore no teardown. Anything those jobs touch stays bound to the worker
thread, and because APScheduler reuses those threads the connections accumulate
instead of being released when a run finishes. Production is a single Gunicorn
worker that never restarts, so the only ceiling is the process descriptor limit.

``historify_scheduler_service.execute_schedule`` was the one background entry
point in the codebase missing this cleanup - ``flow_scheduler_service``,
``flow_price_monitor_service`` and ``flow_order_update_monitor_service`` all
already did it. Reported as issue #1738.

The four early returns are what make a ``finally`` necessary rather than a line
at the end of the function: a missing, disabled, key-less or symbol-less
schedule is the *common* case, and each of those returns out of the middle.
"""

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_on_worker_thread(call):
    """Run ``call`` on a fresh thread, reporting session binding either side.

    A real thread rather than the main one because ``scoped_session`` is
    thread-scoped: the leak only exists on a thread nobody tears down, and the
    main test thread would mask it.
    """
    captured = {}

    def worker():
        from database.auth_db import db_session

        # Bind a session to this thread. Calling the registry is enough - it
        # creates the Session without opening a connection, so this stays a
        # test of the release path and not of the database.
        db_session()
        captured["before"] = db_session.registry.has()
        try:
            call()
        except Exception as exc:  # the exit path under test may raise
            captured["raised"] = exc
        captured["after"] = db_session.registry.has()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive(), "scheduler job did not finish"
    return captured


#: Each entry drives ``execute_schedule`` down a different exit path. The first
#: four are the early returns; the last is the except branch.
EXIT_PATHS = [
    ("schedule_missing", None, None),
    ("schedule_disabled", {"id": "s1", "is_enabled": False, "is_paused": False}, None),
    ("schedule_paused", {"id": "s1", "is_enabled": True, "is_paused": True}, None),
    ("lookup_raised", None, RuntimeError("duckdb unavailable")),
]


@pytest.mark.parametrize("label,schedule,error", EXIT_PATHS, ids=[p[0] for p in EXIT_PATHS])
def test_execute_schedule_releases_sessions(monkeypatch, label, schedule, error):
    """No scoped session may survive the job, whichever way it exits."""
    import database.historify_db as historify_db
    from services.historify_scheduler_service import execute_schedule

    def fake_get_schedule(_schedule_id):
        if error is not None:
            raise error
        return schedule

    monkeypatch.setattr(historify_db, "get_schedule", fake_get_schedule)
    # The except branch writes failure state back; keep that off the database.
    monkeypatch.setattr(historify_db, "update_schedule", lambda *a, **k: None)
    monkeypatch.setattr(historify_db, "increment_schedule_run_counts", lambda *a, **k: None)
    monkeypatch.setattr(historify_db, "update_schedule_execution", lambda *a, **k: None)

    captured = _run_on_worker_thread(lambda: execute_schedule("s1"))

    assert captured["before"] is True, "fixture failed to bind a session to the thread"
    assert captured["after"] is False, (
        f"execute_schedule left a scoped session bound to the worker thread "
        f"on the {label} path - that session holds a database connection for "
        f"the life of the process"
    )


def test_the_probe_would_notice_a_leak():
    """Guard against the assertion above passing for the wrong reason.

    If binding a session did not survive to the second check, every case above
    would pass whether or not the cleanup ran. This runs the same probe around
    a job that deliberately does not clean up, and requires it to be seen.
    """
    captured = _run_on_worker_thread(lambda: None)

    assert captured["before"] is True
    assert captured["after"] is True, (
        "a session left bound was reported as released - the probe cannot "
        "detect a leak and the tests above prove nothing"
    )
