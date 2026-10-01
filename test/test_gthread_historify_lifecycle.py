"""Historify retries and final-item cancellation must leave the worker usable."""

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _child(tmp_path, body, *, eventlet=False):
    env = os.environ.copy()
    env["HISTORIFY_DATABASE_PATH"] = str(tmp_path / "historify.duckdb")
    env["LOG_DIR"] = str(tmp_path / "log")
    env["DATABASE_URL"] = "sqlite:///" + str(tmp_path / "openalgo.db")
    preamble = "import eventlet; eventlet.monkey_patch()\n" if eventlet else ""
    preamble += """
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
dotenv.main.load_dotenv = dotenv.load_dotenv
"""
    result = subprocess.run(
        [sys.executable, "-u", "-c", preamble + textwrap.dedent(body)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout, result.stdout + result.stderr


@pytest.mark.skipif(importlib.util.find_spec("eventlet") is None, reason="requires eventlet")
def test_connection_retry_allows_green_and_native_writers_without_stopping_hub(tmp_path):
    _child(
        tmp_path,
        """
        import duckdb
        import time
        from database import historify_db as db
        from utils import real_threading

        real_threading.start_hub_worker()
        db.init_database()
        original_connect = duckdb.connect
        retried = real_threading.Event()
        attempts = []

        def connect(*a, **k):
            attempts.append(1)
            if len(attempts) == 1:
                retried.set()
                raise OSError("temporary connection failure")
            return original_connect(*a, **k)

        duckdb.connect = connect
        results = []
        first = eventlet.spawn(lambda: results.append(db.add_to_watchlist("SBIN", "NSE")))
        assert real_threading.wait_for(retried, 2)
        second = eventlet.spawn(lambda: results.append(db.add_to_watchlist("INFY", "NSE")))
        native = real_threading.Thread(
            target=lambda: results.append(db.add_to_watchlist("TCS", "NSE")), daemon=True
        )
        native.start()
        heartbeats = []
        def beat():
            for _ in range(10):
                heartbeats.append(1)
                eventlet.sleep(0.02)
        pulse = eventlet.spawn(beat)
        first.wait()
        second.wait()
        assert real_threading.join(native, 3), "native writer could not finish"
        pulse.wait()
        assert len(results) == 3 and all(ok for ok, _ in results), results
        assert {row["symbol"] for row in db.get_watchlist()} == {"SBIN", "INFY", "TCS"}
        assert len(heartbeats) == 10
        print("OK")
        """,
        eventlet=True,
    )


@pytest.mark.parametrize("stop", ["cancel", "shutdown"])
def test_final_item_pause_can_be_cancelled_or_stopped_without_stranding_registry(tmp_path, stop):
    _child(
        tmp_path,
        textwrap.dedent("""
        import threading
        from database import historify_db as db
        db.init_database()
        from services import historify_service as hs

        assert db.create_download_job(
            "last", "custom", [{"symbol": "SBIN", "exchange": "NSE"}],
            "D", "2026-01-01", "2026-01-02"
        )[0]
        item = db.get_job_items("last")[0]
        db.update_job_item_status(item["id"], "success", 1)
        reached = threading.Event()
        hs._emit_job_paused = lambda *args: reached.set()
        hs._emit_job_complete = lambda *args: None
        hs._emit_job_cancelled = lambda *args: None
        hs._running_jobs["last"] = True
        hs._paused_jobs["last"] = threading.Event()
        worker = threading.Thread(target=hs._process_download_job, args=("last", "unused"), daemon=True)
        worker.start()
        assert reached.wait(3), "processor never reached final pause"
        """)
        + (
            '\nassert hs.cancel_job("last")[2] == 200\n'
            if stop == "cancel"
            else "\nhs.stop_all_download_jobs()\n"
        )
        + """
worker.join(3)
assert not worker.is_alive(), "processor deadlocked while cleaning up its own claim"
assert not hs._job_state_lock.locked(), "registry lock left held"
assert "last" not in hs._running_jobs
assert "last" not in hs._paused_jobs
assert db.get_download_job("last")["status"] == "cancelled"
print("OK")
""",
    )


def test_pause_during_final_check_keeps_a_processor_to_resume(tmp_path):
    _child(
        tmp_path,
        """
        import threading
        from database import historify_db as db
        db.init_database()
        from services import historify_service as hs

        assert db.create_download_job(
            "last", "custom", [{"symbol": "SBIN", "exchange": "NSE"}],
            "D", "2026-01-01", "2026-01-02"
        )[0]
        item = db.get_job_items("last")[0]
        db.update_job_item_status(item["id"], "success", 1)
        hs._emit_job_paused = lambda *args: None
        hs._emit_job_complete = lambda *args: None

        checked = threading.Event()
        release_check = threading.Event()
        cleared = threading.Event()
        class PauseGate:
            def __init__(self):
                self.event = threading.Event()
                self.event.set()
            def is_set(self):
                value = self.event.is_set()
                if threading.current_thread() is worker and not checked.is_set():
                    checked.set()
                    assert release_check.wait(3)
                return value
            def clear(self):
                self.event.clear()
                cleared.set()
            def set(self):
                self.event.set()
            def wait(self, timeout=None):
                return self.event.wait(timeout)

        hs._running_jobs["last"] = True
        hs._paused_jobs["last"] = PauseGate()
        worker = threading.Thread(target=hs._process_download_job, args=("last", "unused"), daemon=True)
        worker.start()
        assert checked.wait(3), "processor did not reach final pause check"

        original_update = db.update_job_status
        terminal_written = threading.Event()
        def update(job_id, status, *args):
            if status == "paused":
                terminal_written.wait(1)
            result = original_update(job_id, status, *args)
            if status in ("completed", "completed_with_errors"):
                terminal_written.set()
            return result
        db.update_job_status = update
        pause_result = []
        pauser = threading.Thread(target=lambda: pause_result.append(hs.pause_job("last")), daemon=True)
        pauser.start()
        # On the old path the final check runs outside the registry lock, so
        # pause clears the event here. On the fixed path the claim is atomic
        # with that check and pause may instead be refused after completion.
        cleared.wait(0.3)
        release_check.set()
        pauser.join(3)
        assert not pauser.is_alive()
        if pause_result[0][2] == 200:
            assert db.get_download_job("last")["status"] == "paused"
            assert worker.is_alive(), "pause left no processor to resume"
            assert hs.resume_job("last")[2] == 200
        else:
            assert pause_result[0][2] == 400
        worker.join(3)
        assert not worker.is_alive()
        assert db.get_download_job("last")["status"] == "completed"
        print("OK")
        """,
    )


def test_resume_cannot_write_running_after_terminal_completion(tmp_path):
    _child(
        tmp_path,
        """
        import threading
        from database import historify_db as db
        db.init_database()
        from services import historify_service as hs

        assert db.create_download_job(
            "last", "custom", [{"symbol": "SBIN", "exchange": "NSE"}],
            "D", "2026-01-01", "2026-01-02"
        )[0]
        item = db.get_job_items("last")[0]
        db.update_job_item_status(item["id"], "success", 1)
        paused = threading.Event()
        hs._emit_job_paused = lambda *args: paused.set()
        hs._emit_job_complete = lambda *args: None
        hs._running_jobs["last"] = True
        hs._paused_jobs["last"] = threading.Event()
        worker = threading.Thread(target=hs._process_download_job, args=("last", "unused"), daemon=True)
        worker.start()
        assert paused.wait(3)
        db.update_job_status("last", "paused")

        original_update = db.update_job_status
        completed = threading.Event()
        def update(job_id, status, *args):
            if status == "running" and threading.current_thread() is resumer:
                completed.wait(1)
            result = original_update(job_id, status, *args)
            if status in ("completed", "completed_with_errors"):
                completed.set()
            return result
        db.update_job_status = update
        results = []
        resumer = threading.Thread(target=lambda: results.append(hs.resume_job("last")), daemon=True)
        resumer.start()
        resumer.join(3)
        worker.join(3)
        assert not resumer.is_alive() and not worker.is_alive()
        assert results[0][2] == 200
        assert db.get_download_job("last")["status"] == "completed"
        print("OK")
        """,
    )
