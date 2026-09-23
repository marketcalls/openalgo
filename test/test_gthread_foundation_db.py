"""Session release, the event bus lanes, and the check-then-act fixes.

Each fix here closes a race without changing what happens when nothing races:

* scoped sessions opened off a request (event bus workers, scheduler jobs,
  broker master-contract sessions on pooled request threads) are released;
* a critical subscriber is never shed with the best-effort ones;
* approving, rejecting and claiming an Action Center order is one conditional
  UPDATE, so of several racing callers exactly one wins;
* a master contract download is single flight per broker;
* every .env writer goes through one lock, and a save reaches the value the
  app reads even when the key is assigned twice;
* the version check is unchanged: an outdated .env still stops a server that
  has no terminal to answer the prompt, as it always has.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

import database.action_center_db as action_center_db
from utils import auth_utils, db_sessions, env_check
from utils.event_bus import Event, EventBus

REPO = Path(__file__).resolve().parents[1]


def _run_all(target, count=8, timeout=60):
    barrier = threading.Barrier(count)
    errors = []

    def runner(index):
        try:
            target(index, barrier)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
        assert not thread.is_alive(), "a worker thread hung"
    assert errors == [], errors[:3]


def _sqlite_session(tmp_path: Path, name: str):
    engine = create_engine(
        f"sqlite:///{(tmp_path / name).as_posix()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    return engine, scoped_session(sessionmaker(bind=engine))


# --- db_sessions -------------------------------------------------------------


def test_a_broker_master_contract_session_is_released(tmp_path, monkeypatch):
    """A pooled request thread must not keep a broker's session between requests."""
    engine, session = _sqlite_session(tmp_path, "mc.db")
    fake = types.ModuleType("broker.fakebroker.database.master_contract_db")
    fake.db_session = session
    monkeypatch.setitem(sys.modules, fake.__name__, fake)

    outcome = {}

    def request_thread():
        session.execute(text("SELECT 1"))
        outcome["bound"] = session.registry.has()
        db_sessions.remove_all_scoped_sessions()
        outcome["after"] = session.registry.has()

    thread = threading.Thread(target=request_thread)
    thread.start()
    thread.join(10)
    engine.dispose()
    assert outcome == {"bound": True, "after": False}


def test_registered_sessions_and_the_cleanup_helpers(tmp_path, monkeypatch):
    engine, session = _sqlite_session(tmp_path, "extra.db")
    fake = types.ModuleType("openalgo_test_extra_db")
    fake.extra_session = session
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(db_sessions, "_registered", [])

    db_sessions.register_scoped_session(fake.__name__, "extra_session")
    db_sessions.register_scoped_session(fake.__name__, "extra_session")
    assert db_sessions._registered == [(fake.__name__, "extra_session")]

    with db_sessions.session_cleanup():
        session.execute(text("SELECT 1"))
        assert session.registry.has()
    assert not session.registry.has()

    @db_sessions.releases_scoped_sessions
    def job():
        """A scheduler job."""
        session.execute(text("SELECT 1"))
        raise RuntimeError("job failed")

    assert job.__doc__ == "A scheduler job."
    with pytest.raises(RuntimeError):
        job()
    assert not session.registry.has(), "a failing job must still release its session"
    engine.dispose()


def test_a_module_that_was_never_imported_is_not_imported_to_clean_it(monkeypatch):
    monkeypatch.setattr(db_sessions, "_registered", [("openalgo_never_imported_module", "s")])
    db_sessions.remove_all_scoped_sessions()
    assert "openalgo_never_imported_module" not in sys.modules


# --- event bus ---------------------------------------------------------------


def test_the_bus_releases_sessions_after_every_callback(tmp_path, monkeypatch):
    engine, session = _sqlite_session(tmp_path, "bus.db")
    fake = types.ModuleType("openalgo_test_bus_db")
    fake.db_session = session
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(db_sessions, "_registered", [(fake.__name__, "db_session")])

    bus = EventBus(workers=1)  # one worker: both callbacks share a thread
    seen = []
    bus.subscribe("t", lambda e: session.execute(text("SELECT 1")))
    bus.subscribe("probe", lambda e: seen.append(session.registry.has()))
    bus.publish(Event(topic="t"))
    bus.publish(Event(topic="probe"))
    bus._executor.shutdown(wait=True)
    engine.dispose()
    assert seen == [False], "the second callback inherited the first one's session"


def test_critical_subscribers_are_not_shed_with_best_effort_ones():
    bus = EventBus(workers=2, max_pending=10)
    gate = threading.Event()
    booked = []
    lock = threading.Lock()

    def slow_alert(_event):
        gate.wait(30)

    def book_fill(_event):
        with lock:
            booked.append(1)

    bus.subscribe("order.update", slow_alert, name="TelegramAlert")
    bus.subscribe("order.update", book_fill, name="StrategyBookFills", critical=True)
    try:
        for _ in range(1500):
            bus.publish(Event(topic="order.update"))
        stats = bus.stats()
        assert stats["dropped"] > 0, "the best-effort lane should have shed load"
        assert stats["critical_dropped"] == 0
    finally:
        gate.set()
        bus._executor.shutdown(wait=True)
        bus._critical_executor.shutdown(wait=True)
    assert len(booked) == 1500, f"critical subscriber ran {len(booked)} of 1500 times"
    assert bus.stats()["critical_pending"] == 0


def test_a_critical_overflow_is_logged_as_an_error_every_time(monkeypatch):
    errors = []
    fake_logger = types.SimpleNamespace(
        error=lambda msg, *a, **k: errors.append(msg),
        warning=lambda *a, **k: None,
        exception=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    import utils.event_bus as event_bus_module

    monkeypatch.setattr(event_bus_module, "logger", fake_logger)
    bus = EventBus(critical_workers=1, critical_max_pending=5)
    gate = threading.Event()
    bus.subscribe("t", lambda e: gate.wait(30), name="Book", critical=True)
    try:
        for _ in range(20):
            bus.publish(Event(topic="t"))
        assert bus.stats()["critical_dropped"] == 15
        assert len(errors) == 15 and "Book" in errors[0]
    finally:
        gate.set()
        bus._critical_executor.shutdown(wait=True)
        bus._executor.shutdown(wait=True)


def test_unsubscribe_removes_a_critical_or_plain_subscription():
    bus = EventBus(workers=1)
    calls = []

    def plain(_e):
        calls.append("plain")

    def critical(_e):
        calls.append("critical")

    bus.subscribe("t", plain)
    bus.subscribe("t", critical, critical=True)
    bus.unsubscribe("t", critical)
    bus.unsubscribe("t", lambda e: None)  # not subscribed: ignored
    bus.publish(Event(topic="t"))
    bus._executor.shutdown(wait=True)
    bus._critical_executor.shutdown(wait=True)
    assert calls == ["plain"]


# --- Action Center compare-and-set ------------------------------------------


@pytest.fixture
def action_center(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'action-center.db').as_posix()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    original_query = action_center_db.Base.__dict__["query"]
    monkeypatch.setattr(action_center_db, "engine", engine)
    monkeypatch.setattr(action_center_db, "db_session", session)
    action_center_db.Base.query = session.query_property()
    action_center_db.Base.metadata.create_all(bind=engine)
    try:
        yield action_center_db
    finally:
        session.remove()
        engine.dispose()
        action_center_db.Base.query = original_query


def _new_order(ac):
    return ac.create_pending_order("trader", "placeorder", {"symbol": "SBIN", "quantity": 1})


def _released(fn):
    """Run ``fn`` and release this thread's session, as a request teardown would."""

    def wrapper(*args):
        try:
            return fn(*args)
        finally:
            action_center_db.db_session.remove()

    return wrapper


def test_the_non_racing_approve_and_reject_behave_as_before(action_center):
    order_id = _new_order(action_center)
    assert action_center.approve_pending_order(order_id, "trader", "trader") is True
    order = action_center.get_pending_order_by_id(order_id)
    assert order.status == "approved" and order.approved_by == "trader"
    assert order.approved_at is not None and order.approved_at_ist.endswith("IST")
    assert action_center.approve_pending_order(order_id, "trader", "trader") is False
    assert action_center.reject_pending_order(order_id, "late", "trader", "trader") is False

    other = _new_order(action_center)
    assert action_center.approve_pending_order(other, "trader", "someone-else") is False
    assert action_center.reject_pending_order(other, "no", "trader", "trader") is True
    rejected = action_center.get_pending_order_by_id(other)
    assert rejected.status == "rejected" and rejected.rejected_reason == "no"
    assert action_center.approve_pending_order(999999, "trader", "trader") is False


def test_racing_approvals_let_exactly_one_through(action_center):
    order_id = _new_order(action_center)
    results = []
    lock = threading.Lock()

    @_released
    def approve():
        return action_center.approve_pending_order(order_id, "trader", "trader")

    def worker(_index, barrier):
        barrier.wait()
        outcome = approve()
        with lock:
            results.append(outcome)

    _run_all(worker)
    assert results.count(True) == 1, results


def test_an_approval_racing_a_rejection_has_one_winner(action_center):
    order_id = _new_order(action_center)
    results = []
    lock = threading.Lock()

    @_released
    def approve():
        return ("approve", action_center.approve_pending_order(order_id, "t", "trader"))

    @_released
    def reject():
        return ("reject", action_center.reject_pending_order(order_id, "r", "t", "trader"))

    def worker(index, barrier):
        barrier.wait()
        outcome = approve() if index % 2 else reject()
        with lock:
            results.append(outcome)

    _run_all(worker)
    winners = [name for name, ok in results if ok]
    assert len(winners) == 1, results
    final = action_center.get_pending_order_by_id(order_id).status
    assert final == ("approved" if winners[0] == "approve" else "rejected")


def test_an_approved_order_is_claimed_for_the_broker_once(action_center):
    order_id = _new_order(action_center)
    assert action_center.claim_pending_order_for_execution(order_id) is False, "still pending"
    assert action_center.approve_pending_order(order_id, "trader", "trader") is True
    results = []
    lock = threading.Lock()

    @_released
    def claim():
        return action_center.claim_pending_order_for_execution(order_id)

    def worker(_index, barrier):
        barrier.wait()
        outcome = claim()
        with lock:
            results.append(outcome)

    _run_all(worker)
    assert results.count(True) == 1, results
    order = action_center.get_pending_order_by_id(order_id)
    assert order.broker_status == action_center.SUBMITTING
    assert action_center.claim_pending_order_for_execution(order_id) is False


# --- master contract single flight ------------------------------------------


@pytest.fixture
def blocking_download(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    runs = []

    def fake_download(broker):
        runs.append(broker)
        started.set()
        release.wait(10)
        return {"status": "success"}

    monkeypatch.setattr(auth_utils, "_download_master_contract", fake_download)
    monkeypatch.setattr(auth_utils, "_master_contract_running", set())
    yield types.SimpleNamespace(started=started, release=release, runs=runs)
    release.set()


def test_a_second_start_while_one_runs_is_refused(blocking_download):
    assert auth_utils.try_start_master_contract_download("zerodha") is True
    assert blocking_download.started.wait(5)
    assert auth_utils.is_master_contract_download_running("zerodha") is True
    assert auth_utils.try_start_master_contract_download("zerodha") is False
    refused = auth_utils.async_master_contract_download("zerodha")
    assert refused["status"] == "error" and "already running" in refused["message"]
    # Another broker is not blocked by this one.
    assert auth_utils.is_master_contract_download_running("angel") is False

    blocking_download.release.set()
    deadline = time.monotonic() + 5
    while auth_utils.is_master_contract_download_running("zerodha") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert auth_utils.is_master_contract_download_running("zerodha") is False
    assert blocking_download.runs == ["zerodha"]


def test_simultaneous_starts_start_one_download(blocking_download):
    results = []
    lock = threading.Lock()

    def worker(_index, barrier):
        barrier.wait()
        outcome = auth_utils.try_start_master_contract_download("zerodha")
        with lock:
            results.append(outcome)

    _run_all(worker)
    assert results.count(True) == 1, results


def test_a_non_overlapping_download_runs_and_releases_its_claim(monkeypatch):
    monkeypatch.setattr(auth_utils, "_master_contract_running", set())
    monkeypatch.setattr(
        auth_utils, "_download_master_contract", lambda broker: {"status": "success"}
    )
    assert auth_utils.async_master_contract_download("zerodha") == {"status": "success"}
    assert auth_utils.is_master_contract_download_running("zerodha") is False

    def boom(broker):
        raise RuntimeError("download crashed")

    monkeypatch.setattr(auth_utils, "_download_master_contract", boom)
    with pytest.raises(RuntimeError):
        auth_utils.async_master_contract_download("zerodha")
    assert auth_utils.is_master_contract_download_running("zerodha") is False


# --- .env writes and the version check ---------------------------------------


def test_update_env_values_replaces_appends_and_keeps_line_endings(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(
        b"# comment\r\nMCP_HTTP_ENABLED = 'False'\r\nOTHER='x'\r\nMCP_HTTP_ENABLED = 'dup'"
    )
    env_check.update_env_values(
        str(env),
        {"MCP_HTTP_ENABLED": "True", "MCP_PUBLIC_URL": "https://example.test", "Q": "it's"},
    )
    content = env.read_bytes().decode()
    assert content.startswith(
        "# comment\r\nMCP_HTTP_ENABLED = 'True'\r\nOTHER='x'\r\nMCP_HTTP_ENABLED = 'True'\r\n"
    )
    assert "MCP_PUBLIC_URL = 'https://example.test'\r\n" in content
    assert 'Q = "it\'s"\r\n' in content
    assert "\n" not in content.replace("\r\n", "")


def test_a_duplicated_key_is_saved_where_the_app_reads_it(tmp_path):
    """python-dotenv applies the last assignment, so every one must change.

    A .env with a key assigned twice is what pasting a block from .sample.env
    leaves behind. Replacing only the first line reported a save that the app
    never saw. A commented-out line is documentation and stays as it was.
    """
    from dotenv import dotenv_values

    env = tmp_path / ".env"
    env.write_text(
        "BROKER_API_KEY = 'old1'\n"
        "# BROKER_API_KEY = 'example'\n"
        "OTHER = 'x'\n"
        "BROKER_API_KEY = 'old2'\n"
        "export BROKER_API_KEY='old3'\n",
        encoding="utf-8",
    )
    env_check.update_env_values(str(env), {"BROKER_API_KEY": "new"})
    assert dotenv_values(env)["BROKER_API_KEY"] == "new"
    content = env.read_text(encoding="utf-8")
    assert "# BROKER_API_KEY = 'example'\n" in content
    assert "old1" not in content and "old2" not in content and "old3" not in content
    assert content.count("BROKER_API_KEY = 'new'") == 3


def test_update_env_values_refuses_bad_keys_and_line_breaks(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A = '1'\n", encoding="utf-8")
    with pytest.raises(ValueError):
        env_check.update_env_values(str(env), {"BAD KEY": "1"})
    with pytest.raises(ValueError):
        env_check.update_env_values(str(env), {"A": "1\nINJECTED=2"})
    assert env.read_text(encoding="utf-8") == "A = '1'\n"


def test_concurrent_env_saves_lose_no_update(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ENV_CONFIG_VERSION = '1.0.0'\n", encoding="utf-8")

    def worker(index, barrier):
        barrier.wait()
        for n in range(5):
            env_check.update_env_values(str(env), {f"KEY_{index}_{n}": str(n)})

    _run_all(worker)
    content = env.read_text(encoding="utf-8")
    missing = [
        f"KEY_{i}_{n}" for i in range(8) for n in range(5) if f"KEY_{i}_{n} = '{n}'" not in content
    ]
    assert missing == [], f"lost updates: {missing}"


def _load_env_check_copy(tmp_path, env_version, sample_version):
    """A copy of env_check whose .env and .sample.env live in tmp_path."""
    (tmp_path / "utils").mkdir()
    shutil.copy(REPO / "utils" / "env_check.py", tmp_path / "utils" / "env_check.py")
    (tmp_path / ".env").write_text(f"ENV_CONFIG_VERSION = '{env_version}'\n", encoding="utf-8")
    (tmp_path / ".sample.env").write_text(
        f"ENV_CONFIG_VERSION = '{sample_version}'\n", encoding="utf-8"
    )
    spec = importlib.util.spec_from_file_location(
        "env_check_copy", tmp_path / "utils" / "env_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Stdin:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


def test_an_outdated_env_on_a_headless_server_still_refuses_to_start(tmp_path, monkeypatch):
    """The default install sees no change: an outdated .env still stops startup.

    Under systemd stdin is /dev/null, so the prompt's input() raises EOFError
    and the check returns False, which makes the worker refuse to boot until
    the operator updates .env. That is how it behaved before the gthread work,
    and how it must keep behaving on every install that has not opted in.
    """
    module = _load_env_check_copy(tmp_path, "1.0.0", "9.9.9")
    monkeypatch.setattr(sys, "stdin", _Stdin(False))
    prompts = []

    def no_terminal(*args):
        prompts.append(args)
        raise EOFError

    monkeypatch.setattr("builtins.input", no_terminal)
    assert module.check_env_version_compatibility() is False
    assert len(prompts) == 1, "the prompt was skipped instead of answered with end of file"


def test_an_outdated_env_at_a_terminal_still_asks(tmp_path, monkeypatch):
    module = _load_env_check_copy(tmp_path, "1.0.0", "9.9.9")
    monkeypatch.setattr(sys, "stdin", _Stdin(True))
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    assert module.check_env_version_compatibility() is False
    monkeypatch.setattr("builtins.input", lambda *_a: "y")
    assert module.check_env_version_compatibility() is True
