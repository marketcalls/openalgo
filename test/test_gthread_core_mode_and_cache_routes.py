"""The analyzer mode and the sandbox engine change together; cache reloads wait for downloads.

rest-06: three places changed the analyzer (sandbox) mode, each writing the
mode and then starting or stopping the sandbox execution engine and square-off
scheduler as two separate steps. Two requests (a double click, two devices)
could interleave them and leave Live mode with the sandbox engine running, or
Sandbox mode with the engine stopped, so sandbox SL and LIMIT orders never
triggered. apply_analyze_mode() now does both under one lock and reconciles
the engine to the mode actually persisted.

rest-05 (route half): a manual symbol cache reload or clear during a master
contract download is refused under gthread, where it would load the half
rewritten table; elsewhere the routes behave as before.
"""

from __future__ import annotations

import threading
import time

import pytest

import services.analyzer_service as analyzer_service
from utils import runtime
from utils.keyed_locks import LockBusy


class FakeSandbox:
    """In-memory mode flag and engine state, recording overlap."""

    def __init__(self):
        self.persisted = False
        self.engine_running = False
        self.scheduler_running = False
        self.inside = 0
        self.max_inside = 0
        self.lock = threading.Lock()
        self.fail_after_write = False
        self.catchups = 0

    def enter(self):
        with self.lock:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)

    def leave(self):
        with self.lock:
            self.inside -= 1

    def get_analyze_mode(self):
        return self.persisted

    def set_analyze_mode(self, mode):
        self.enter()
        try:
            time.sleep(0.005)
            self.persisted = bool(mode)
            if self.fail_after_write:
                raise KeyError("analyze_mode")  # the old post-commit cache delete
        finally:
            self.leave()

    def start_engine(self, *args):
        self.enter()
        time.sleep(0.002)
        self.engine_running = True
        self.leave()
        return True, "started"

    def stop_engine(self):
        self.enter()
        time.sleep(0.002)
        self.engine_running = False
        self.leave()
        return True, "stopped"

    def start_scheduler(self):
        self.scheduler_running = True
        return True, "started"

    def stop_scheduler(self, wait=True):
        self.scheduler_running = False
        return True, "stopped"

    def catchup(self):
        self.catchups += 1


@pytest.fixture
def sandbox(monkeypatch):
    import sandbox.execution_thread as execution_thread
    import sandbox.position_manager as position_manager
    import sandbox.squareoff_thread as squareoff_thread

    fake = FakeSandbox()
    monkeypatch.setattr(analyzer_service, "get_analyze_mode", fake.get_analyze_mode)
    monkeypatch.setattr(analyzer_service, "set_analyze_mode", fake.set_analyze_mode)
    monkeypatch.setattr(execution_thread, "start_execution_engine", fake.start_engine)
    monkeypatch.setattr(execution_thread, "stop_execution_engine", fake.stop_engine)
    monkeypatch.setattr(squareoff_thread, "start_squareoff_scheduler", fake.start_scheduler)
    monkeypatch.setattr(squareoff_thread, "stop_squareoff_scheduler", fake.stop_scheduler)
    monkeypatch.setattr(position_manager, "catchup_missed_settlements", fake.catchup)
    return fake


def test_racing_mode_changes_leave_the_engine_matching_the_mode(sandbox):
    barrier = threading.Barrier(16)
    errors = []

    def change(index):
        try:
            barrier.wait()
            if index % 3 == 0:
                analyzer_service.apply_analyze_mode(toggle=True)
            else:
                analyzer_service.apply_analyze_mode(bool(index % 2))
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=change, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert errors == []
    # One change at a time, and the machinery ends where the mode ends.
    assert sandbox.max_inside == 1
    assert sandbox.engine_running == sandbox.scheduler_running == sandbox.persisted


def test_a_write_that_raises_still_leaves_the_engine_matching(sandbox):
    sandbox.fail_after_write = True
    with pytest.raises(KeyError):
        analyzer_service.apply_analyze_mode(True)
    # The mode was written before the failure; the engine follows it.
    assert sandbox.persisted is True
    assert sandbox.engine_running is True and sandbox.scheduler_running is True


def test_the_quiet_path_does_what_each_caller_did_before(sandbox):
    assert analyzer_service.apply_analyze_mode(True) is True
    assert sandbox.engine_running and sandbox.scheduler_running and sandbox.catchups == 1
    assert analyzer_service.apply_analyze_mode(toggle=True) is False
    assert not sandbox.engine_running and not sandbox.scheduler_running

    # The settings route only ever managed the engine.
    assert analyzer_service.apply_analyze_mode(True, with_scheduler=False, catchup=False) is True
    assert sandbox.engine_running is True
    assert sandbox.scheduler_running is False
    assert sandbox.catchups == 1


def test_only_gthread_refuses_a_change_that_waits_too_long(sandbox, monkeypatch):
    held = threading.Event()
    release = threading.Event()

    def holder():
        with analyzer_service.mode_transition():
            held.set()
            release.wait(10)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(5)
    try:
        monkeypatch.setattr(runtime, "gthread_active", lambda: True)
        with pytest.raises(LockBusy) as busy:
            analyzer_service.apply_analyze_mode(True, timeout=0.05)
        assert "Try again" in str(busy.value)

        # Under eventlet and the dev server the change waits its turn instead.
        monkeypatch.setattr(runtime, "gthread_active", lambda: False)
        outcome = []
        waiter = threading.Thread(
            target=lambda: outcome.append(analyzer_service.apply_analyze_mode(True, timeout=0.05))
        )
        waiter.start()
        time.sleep(0.2)
        assert outcome == []
        release.set()
        waiter.join(10)
        assert outcome == [True]
    finally:
        release.set()
        thread.join(10)


def test_the_session_toggle_route_answers_busy_with_a_sentence(sandbox, monkeypatch):
    from flask import Flask

    import blueprints.auth as auth_bp_module
    import utils.session as session_utils

    monkeypatch.setattr(session_utils, "is_session_valid", lambda: True)

    def busy(*args, **kwargs):
        raise LockBusy("analyze_mode", name="analyzer-mode", timeout=30)

    monkeypatch.setattr(analyzer_service, "apply_analyze_mode", busy)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(auth_bp_module.auth_bp)
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "u"
            sess["logged_in"] = True
        response = client.post("/auth/analyzer-toggle", headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 409
    assert response.get_json()["message"] == analyzer_service.MODE_BUSY_MESSAGE


# --- rest-05, the route half ------------------------------------------------------


@pytest.fixture
def cache_client(monkeypatch):
    from flask import Flask

    import blueprints.master_contract_status as mcs
    import database.master_contract_cache_hook as hook
    import database.token_db_enhanced as tde
    import utils.session as session_utils
    from utils import auth_utils

    monkeypatch.setattr(session_utils, "is_session_valid", lambda: True)
    monkeypatch.setattr(auth_utils, "_master_contract_running", {"zerodha"})
    reloads = []
    clears = []
    monkeypatch.setattr(hook, "load_symbols_to_cache", lambda broker: reloads.append(broker) or True)
    monkeypatch.setattr(tde, "clear_cache", lambda: clears.append(1))
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(mcs.master_contract_status_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["broker"] = "zerodha"
    return client, mcs, reloads, clears


def test_gthread_refuses_a_cache_reload_during_a_download(cache_client, monkeypatch):
    client, mcs, reloads, clears = cache_client
    monkeypatch.setattr(mcs, "gthread_active", lambda: True)

    for url in ("/api/cache/reload", "/api/cache/clear"):
        response = client.post(url)
        assert response.status_code == 409
        assert "already running" in response.get_json()["message"]
    assert reloads == [] and clears == []


def test_elsewhere_the_cache_routes_behave_as_before(cache_client, monkeypatch):
    client, mcs, reloads, clears = cache_client
    monkeypatch.setattr(mcs, "gthread_active", lambda: False)

    assert client.post("/api/cache/reload").status_code == 200
    assert client.post("/api/cache/clear").status_code == 200
    assert reloads == ["zerodha"] and clears == [1]
