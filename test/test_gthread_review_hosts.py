"""Strategy host findings from the gthread review.

hosts-messaging-01. Under gthread the early shutdown hook stopped each Python
strategy through the ordinary stop, which wrote is_running False into
strategy_configs.json. The next server start therefore restored nothing, and
a strategy that was running before a routine `systemctl restart` stayed off,
with its positions unmanaged, until its next scheduled start or a manual
Start. Under eventlet the signal handler exits before any cleanup writes the
config, so the record survives and the strategy is restarted at boot. The
gthread shutdown now keeps the record as well. The development server's
atexit cleanup still records the stop, as it always has.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from blueprints import python_strategy as ps


class _NoScheduler:
    running = False


@pytest.fixture
def host(monkeypatch, tmp_path):
    """The strategy host with its files in tmp_path and no real scheduler."""
    monkeypatch.setattr(ps, "CONFIG_FILE", tmp_path / "strategy_configs.json")
    monkeypatch.setattr(ps, "LOGS_DIR", tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(ps, "STRATEGY_CONFIGS", {})
    monkeypatch.setattr(ps, "_SHUTTING_DOWN", threading.Event())
    monkeypatch.setattr(ps, "_SHUTDOWN_KEEPS_RECORDS", threading.Event(), raising=False)
    monkeypatch.setattr(ps, "SCHEDULER", _NoScheduler())
    monkeypatch.setattr(ps, "cleanup_strategy_logs", lambda *a, **k: None)
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda *a, **k: (True, "ready"))
    saved_running = dict(ps.RUNNING_STRATEGIES)
    ps.RUNNING_STRATEGIES.clear()
    children = []
    yield tmp_path, children
    for child in children:
        if child.poll() is None:
            child.kill()
            child.wait(10)
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(saved_running)


def _running_strategy(tmp_path, children, strategy_id="s1"):
    script = tmp_path / f"{strategy_id}.py"
    script.write_text("import time\nwhile True:\n    time.sleep(1)\n", encoding="utf-8")
    # Its own process group, as the host starts every strategy: the stop signals
    # the whole group, which would otherwise include this test run.
    if sys.platform == "win32":
        child = subprocess.Popen(
            [sys.executable, str(script)], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        child = subprocess.Popen([sys.executable, str(script)], start_new_session=True)
    children.append(child)
    ps.STRATEGY_CONFIGS[strategy_id] = {
        "name": strategy_id,
        "file_path": str(script),
        "file_name": script.name,
        "exchange": "NSE",
        "is_running": True,
        "pid": child.pid,
        "is_scheduled": False,
    }
    ps.RUNNING_STRATEGIES[strategy_id] = {
        "process": child,
        "pid": child.pid,
        "started_at": ps.get_ist_time(),
        "log_file": None,
    }
    assert ps.save_configs()
    return child


def _next_server_start(monkeypatch):
    """What the next worker does at boot: load the saved configs, restore."""
    ps.RUNNING_STRATEGIES.clear()
    monkeypatch.setattr(ps, "_SHUTTING_DOWN", threading.Event())
    ps.load_configs()
    started = []
    monkeypatch.setattr(
        ps, "start_strategy_process", lambda sid: started.append(sid) or (True, "started")
    )
    ps.restore_strategy_states()
    return started


def _wait_dead(child, timeout=15):
    deadline = time.monotonic() + timeout
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    return child.poll() is not None


def test_a_gthread_shutdown_stops_the_strategy_and_it_comes_back(host, monkeypatch):
    tmp_path, children = host
    child = _running_strategy(tmp_path, children)

    killed = ps.begin_shutdown(budget_s=10)

    assert killed == []
    assert _wait_dead(child), "the strategy was not stopped"
    assert ps.STRATEGY_CONFIGS["s1"]["is_running"] is True, (
        "the shutdown recorded the strategy as stopped, so the next start restores nothing"
    )
    assert _next_server_start(monkeypatch) == ["s1"]


def test_the_atexit_cleanup_after_a_gthread_shutdown_keeps_the_record(host, monkeypatch):
    """A strategy begin_shutdown could not stop is left for atexit, which must
    not undo the record either."""
    tmp_path, children = host
    child = _running_strategy(tmp_path, children)
    ps._SHUTDOWN_KEEPS_RECORDS.set()

    ps.cleanup_on_exit()

    assert _wait_dead(child)
    assert ps.STRATEGY_CONFIGS["s1"]["is_running"] is True
    assert _next_server_start(monkeypatch) == ["s1"]


def test_without_a_gthread_shutdown_atexit_still_records_the_stop(host, monkeypatch):
    """The development server reaches atexit: unchanged, the stop is recorded."""
    tmp_path, children = host
    child = _running_strategy(tmp_path, children)

    ps.cleanup_on_exit()

    assert _wait_dead(child)
    assert ps.STRATEGY_CONFIGS["s1"]["is_running"] is False
    assert ps.STRATEGY_CONFIGS["s1"]["pid"] is None
    assert _next_server_start(monkeypatch) == []


def test_a_trader_stop_still_records_the_stop(host):
    tmp_path, children = host
    child = _running_strategy(tmp_path, children)

    ok, _message = ps.stop_strategy_process("s1")

    assert ok and _wait_dead(child)
    assert ps.STRATEGY_CONFIGS["s1"]["is_running"] is False


# ---------------------------------------------------------------------------
# hosts-messaging-05: a Historify retry right after a cancel
# ---------------------------------------------------------------------------
#
# cancel_job removed the job from the running registry while its processor was
# still mid-download. A retry landing before the processor's next check found
# no processor, claimed the job and started a second one; the first read the
# retry's claim as "not cancelled" and carried on beside it, and its cleanup
# then removed the retry's claim, so the retried job was marked cancelled.


@pytest.fixture
def historify(monkeypatch):
    import database.historify_db as historify_db
    from services import historify_service as hs

    status = {"value": "running"}
    submitted = []
    monkeypatch.setattr(
        historify_db, "get_download_job", lambda job_id: {"id": job_id, "status": status["value"]}
    )
    monkeypatch.setattr(
        historify_db,
        "update_job_status",
        lambda job_id, value, *a, **k: status.__setitem__("value", value),
    )
    monkeypatch.setattr(
        historify_db,
        "get_job_items",
        lambda job_id, status=None: [{"id": 1, "symbol": "SBIN", "status": "error"}],
    )
    monkeypatch.setattr(historify_db, "update_job_item_status", lambda *a, **k: None)
    monkeypatch.setattr(hs, "_emit_job_cancelled", lambda job_id: None)
    monkeypatch.setattr(hs._job_executor, "submit", lambda fn, *a: submitted.append(a))
    running = dict(hs._running_jobs)
    paused = dict(hs._paused_jobs)
    yield hs, status, submitted
    hs._running_jobs.clear()
    hs._running_jobs.update(running)
    hs._paused_jobs.clear()
    hs._paused_jobs.update(paused)


def _processor_claimed(hs, job_id):
    with hs._job_state_lock:
        hs._running_jobs[job_id] = True
        hs._paused_jobs[job_id] = threading.Event()
        hs._paused_jobs[job_id].set()


def _processor_sees_cancelled(hs, job_id):
    """The exact check the processor makes before each symbol."""
    with hs._job_state_lock:
        return not hs._running_jobs.get(job_id, False)


def test_a_retry_before_the_processor_sees_the_cancel_is_refused(historify):
    hs, status, submitted = historify
    _processor_claimed(hs, "H1")

    assert hs.cancel_job("H1")[2] == 200
    ok, body, code = hs.retry_failed_items("H1", "key")

    assert (ok, code) == (False, 409)
    assert body["message"] == hs.RETRY_BUSY_MESSAGE
    assert submitted == [], "a second processor was started beside the first"
    assert _processor_sees_cancelled(hs, "H1")


def test_once_the_processor_has_left_the_retry_runs(historify):
    hs, status, submitted = historify
    _processor_claimed(hs, "H2")
    assert hs.cancel_job("H2")[2] == 200

    hs._cleanup_job("H2")  # the processor's cancelled path, on its next check
    ok, _body, code = hs.retry_failed_items("H2", "key")

    assert (ok, code) == (True, 200)
    assert len(submitted) == 1
    assert not _processor_sees_cancelled(hs, "H2"), "the retried job reads as cancelled"


def test_cancelling_a_job_no_processor_holds_leaves_nothing_behind(historify):
    hs, status, submitted = historify

    assert hs.cancel_job("H3")[2] == 200

    assert "H3" not in hs._running_jobs
    assert hs.retry_failed_items("H3", "key")[2] == 200


def test_a_processor_that_finds_no_job_releases_its_claim(historify, monkeypatch):
    import database.historify_db as historify_db

    hs, status, submitted = historify
    _processor_claimed(hs, "H4")
    monkeypatch.setattr(historify_db, "get_download_job", lambda job_id: None)

    hs._process_download_job("H4", "key")

    assert "H4" not in hs._running_jobs, "the claim outlived its processor"
