"""Scheduler jobs in the strategy hosts release their sessions and run late (hosts-10, hosts-22).

hosts-10. The strategy host's, the OpenScript runner's and Chartink's jobs
touch scoped sessions (the active broker, the market calendar, Chartink's own
tables, the API key) on APScheduler's threads, which have no request teardown
and are reused, so every session a job bound stayed open on its thread, with
an identity map that could serve a stale row to a later run. Every callable
these files hand to add_job now releases them in a finally.

hosts-22. Neither the strategy host's scheduler (which the OpenScript runner
shares) nor Chartink's set a misfire grace, so APScheduler's one second
applied: with more jobs due on one minute than executor threads, the rest
reached a thread late and were skipped with only a "was missed" warning, a stop
or a square-off included. Under the gthread worker both now allow five minutes;
eventlet and the development server keep APScheduler's defaults, as before
(review eventlet-neutrality-04).
"""

import ast
import inspect
import threading
import time
from datetime import datetime, timedelta

import pytest
from apscheduler.executors.pool import ThreadPoolExecutor as ApsThreadPool
from apscheduler.schedulers.background import BackgroundScheduler

import blueprints.chartink as chartink
import blueprints.openscript_runner as runner
import utils.db_sessions as db_sessions
from blueprints import python_strategy as ps


@pytest.fixture
def released(monkeypatch):
    """Record the thread each session release happens on."""
    threads = []
    monkeypatch.setattr(
        db_sessions, "remove_all_scoped_sessions", lambda: threads.append(threading.get_ident())
    )
    return threads


def _on_fresh_thread(call):
    seen = {}

    def work():
        seen["thread"] = threading.get_ident()
        call()

    worker = threading.Thread(target=work)
    worker.start()
    worker.join(10)
    return seen["thread"]


def test_every_job_releases_its_sessions_on_its_own_thread(released, monkeypatch):
    monkeypatch.setattr(ps, "daily_trading_day_check", lambda: None)
    monkeypatch.setattr(ps, "market_hours_enforcer", lambda: None)
    monkeypatch.setattr(ps, "cleanup_dead_processes", lambda: None)
    monkeypatch.setattr(ps, "scheduled_start_strategy", lambda sid: None)
    monkeypatch.setattr(ps, "scheduled_stop_strategy", lambda sid: None)
    monkeypatch.setattr(runner, "_load_schedules", lambda: {})
    monkeypatch.setattr(runner, "stop_run", lambda *a, **k: (False, "not running"))
    monkeypatch.setattr(runner, "reap_finished_runs", lambda: [])
    monkeypatch.setattr(chartink, "get_strategy", lambda sid: None)
    monkeypatch.setattr(chartink, "restore_squareoff_jobs", lambda: True)

    jobs = [
        ps._run_daily_trading_day_check,
        ps._run_market_hours_enforcer,
        ps._run_dead_process_reaper,
        lambda: ps._run_scheduled_start("x"),
        lambda: ps._run_scheduled_stop("x"),
        lambda: runner._scheduled_start("x.oscript"),
        lambda: runner._scheduled_stop("x.oscript"),
        runner._reap_quietly,
        lambda: chartink.squareoff_positions(1),
        chartink._restore_squareoffs_on_schedule,
    ]
    for job in jobs:
        before = len(released)
        thread = _on_fresh_thread(job)
        assert released[before:] == [thread], f"{job} did not release its sessions"


def _decorated_with_release(tree) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "releases_scoped_sessions":
                    names.add(node.name)
    return names


def _job_callables(tree):
    """(line, callable name) for every add_job call; partials are unwrapped."""
    found = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_job"
        ):
            continue
        target = next((kw.value for kw in node.keywords if kw.arg == "func"), None)
        if target is None and node.args:
            target = node.args[0]
        if isinstance(target, ast.Call):
            called = target.func
            name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
            if name == "partial" and target.args:
                target = target.args[0]
        found.append((node.lineno, target.id if isinstance(target, ast.Name) else ast.dump(target)))
    return found


@pytest.mark.parametrize("module", [ps, runner, chartink])
def test_every_scheduled_callable_releases_sessions(module):
    tree = ast.parse(inspect.getsource(module))
    released_names = _decorated_with_release(tree)
    jobs = _job_callables(tree)
    assert jobs, f"no add_job call found in {module.__name__}"
    unwrapped = [(line, name) for line, name in jobs if name not in released_names]
    assert unwrapped == [], (
        f"{module.__name__} schedules callables that never release their scoped "
        f"sessions: {unwrapped}"
    )


def test_under_gthread_both_schedulers_allow_a_late_job_to_run(monkeypatch):
    for module in (ps, chartink):
        monkeypatch.setattr(module.runtime, "gthread_active", lambda: True)
        defaults = module.scheduler_job_defaults()
        assert defaults["misfire_grace_time"] >= 60
        assert defaults["coalesce"] is True
        assert defaults["max_instances"] == 1


def test_outside_gthread_both_schedulers_keep_apschedulers_defaults():
    """This process is the development server, as the schedulers were built."""
    assert not ps.runtime.gthread_active()
    for module in (ps, chartink):
        assert module.scheduler_job_defaults() == {}
    for scheduler in (ps.SCHEDULER, chartink.scheduler):
        if scheduler is not None:
            assert scheduler._job_defaults["misfire_grace_time"] == 1


def _run_five_simultaneous_jobs(job_defaults) -> int:
    """Five jobs due at one instant on a one thread executor, each taking 0.5s."""
    ran = []
    lock = threading.Lock()

    def job(n):
        time.sleep(0.5)
        with lock:
            ran.append(n)

    scheduler = BackgroundScheduler(
        executors={"default": ApsThreadPool(1)}, job_defaults=job_defaults
    )
    scheduler.start(paused=True)
    when = datetime.now() + timedelta(seconds=0.3)
    for n in range(5):
        scheduler.add_job(job, "date", run_date=when, args=[n], id=f"job{n}")
    scheduler.resume()
    time.sleep(4)
    scheduler.shutdown(wait=True)
    return len(ran)


def test_with_the_defaults_every_simultaneous_job_runs():
    assert _run_five_simultaneous_jobs(dict(ps.SCHEDULER_JOB_DEFAULTS)) == 5
    assert _run_five_simultaneous_jobs(dict(chartink.SCHEDULER_JOB_DEFAULTS)) == 5


def test_apschedulers_own_default_drops_the_late_ones():
    """The defect: with a one second grace the jobs queued behind others are skipped."""
    assert _run_five_simultaneous_jobs({}) < 5
