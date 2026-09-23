"""utils.runtime answers "did eventlet patch this process" without importing it.

The guard it replaces, ``"eventlet" in sys.modules``, answered whether eventlet
had been imported. Under the gthread worker eventlet stays installed as the
fallback, and several modules imported it merely to ask, so the first such
probe flipped every later guard into its eventlet branch in a process nothing
had patched, where ``eventlet.patcher.original("threading")`` then built a
second copy of the threading module.

What is pinned here:

* the detector never imports eventlet, and reports what the patcher says;
* under a real ``eventlet.monkey_patch()`` every swept guard takes exactly the
  branch it took before (subprocess: patching is global and one-way);
* with eventlet imported but not patched, and with a stub eventlet whose
  ``original()`` explodes, every guard takes the stdlib branch;
* no production module compares ``"eventlet"`` against ``sys.modules`` or
  imports eventlet (a tripwire over tracked files);
* every new foundation module imports cleanly in a fresh interpreter, which on
  Windows means without eventlet, fcntl or POSIX-only signals.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from utils import runtime

REPO = Path(__file__).resolve().parents[1]

FOUNDATION_MODULES = [
    "utils.runtime",
    "utils.real_threading",
    "utils.thread_safe_cache",
    "utils.lazy",
    "utils.keyed_locks",
    "utils.stream_registry",
    "utils.shutdown",
    "utils.db_sessions",
    "utils.broker_backpressure",
    "utils.shared_executors",
    "utils.smart_order_guard",
    "utils.env_check",
    "utils.event_bus",
    "extensions",
]

#: Modules whose eventlet guard was swept, and the attribute that guard sets.
GUARDED_THREADING_ATTRS = [
    ("websocket_proxy.app_integration", "_original_threading"),
    ("broker.arrow.streaming.arrow_websocket", "_real_threading"),
    ("broker.dhan_sandbox.streaming.dhan_websocket", "_original_threading"),
    ("broker.hdfcsecurities.api.data", "_real_threading"),
    ("broker.hdfcsecurities.streaming.hdfcsecurities_adapter", "_real_threading"),
    ("broker.hdfcsecurities.streaming.hdfcsecurities_websocket", "_real_threading"),
    ("broker.hdfcsky.api.data", "_real_threading"),
    ("broker.hdfcsky.streaming.hdfcsky_websocket", "_real_threading"),
    ("broker.zerodha.streaming.zerodha_adapter", "_real_threading"),
    ("broker.zerodha.streaming.zerodha_websocket", "_real_threading"),
    ("services.telegram_bot_service", "original_threading"),
]

USE_ASYNC_MODULES = [
    "broker.flattrade.api.data",
    "broker.definedge.api.data",
    "broker.shoonya.api.data",
    "broker.zebu.api.data",
]


def _child_env(tmp_path: Path) -> dict:
    env = dict(os.environ)
    db = tmp_path / "db"
    db.mkdir(exist_ok=True)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "SANDBOX_DATABASE_URL": f"sqlite:///{(db / 'sandbox.db').as_posix()}",
            "LOGS_DATABASE_URL": f"sqlite:///{(db / 'logs.db').as_posix()}",
            "LATENCY_DATABASE_URL": f"sqlite:///{(db / 'latency.db').as_posix()}",
            "HEALTH_DATABASE_URL": f"sqlite:///{(db / 'health.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "LOG_TO_FILE": "False",
            "API_KEY_PEPPER": "0" * 64,
            "APP_KEY": "test-only-app-key",
            "BROKER_API_KEY": "test",
            "BROKER_API_SECRET": "test",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    env.pop("OPENALGO_EFFECTIVE_THREADS", None)
    return env


def _run_child(tmp_path: Path, body: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        cwd=str(REPO),
        env=_child_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _eventlet_installed() -> bool:
    from importlib.util import find_spec

    return find_spec("eventlet") is not None


@pytest.fixture
def clean_runtime(monkeypatch):
    """Keep the cached patch state and any registered worker out of other tests."""
    monkeypatch.setattr(runtime, "_patched", set())
    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.setattr(runtime, "_worker_ref", None)
    monkeypatch.delenv("OPENALGO_EFFECTIVE_THREADS", raising=False)
    monkeypatch.delenv("OPENALGO_WORKER_CLASS", raising=False)
    yield


def _fake_patcher(patched: set[str], originals: dict | None = None):
    module = types.ModuleType("eventlet.patcher")
    module.is_monkey_patched = lambda name: name in patched

    def original(name):
        if originals is None or name not in originals:
            raise AssertionError(f"original({name!r}) was called")
        return originals[name]

    module.original = original
    return module


# --- is_monkey_patched and original -----------------------------------------


def test_unpatched_process_reports_dev_and_never_imports_eventlet(clean_runtime, monkeypatch):
    monkeypatch.delitem(sys.modules, "eventlet.patcher", raising=False)
    assert runtime.is_monkey_patched() is False
    assert runtime.is_monkey_patched("socket") is False
    assert runtime.worker_class() in ("dev", "sync", "gthread")
    assert runtime.original("threading") is __import__("threading")
    assert "eventlet.patcher" not in sys.modules


def test_detector_reports_what_the_patcher_says(clean_runtime, monkeypatch):
    monkeypatch.setitem(sys.modules, "eventlet.patcher", _fake_patcher({"socket"}))
    assert runtime.is_monkey_patched("socket") is True
    assert runtime.is_monkey_patched("thread") is False


def test_a_true_answer_is_cached_because_patching_cannot_be_undone(clean_runtime, monkeypatch):
    monkeypatch.setitem(sys.modules, "eventlet.patcher", _fake_patcher({"thread"}))
    assert runtime.is_monkey_patched() is True
    monkeypatch.delitem(sys.modules, "eventlet.patcher")
    assert runtime.is_monkey_patched() is True


def test_a_patcher_that_raises_counts_as_unpatched(clean_runtime, monkeypatch):
    broken = types.ModuleType("eventlet.patcher")

    def boom(_name):
        raise RuntimeError("broken patcher")

    broken.is_monkey_patched = boom
    monkeypatch.setitem(sys.modules, "eventlet.patcher", broken)
    assert runtime.is_monkey_patched() is False


def test_original_asks_eventlet_only_when_that_module_is_patched(clean_runtime, monkeypatch):
    sentinel = types.ModuleType("fake_original_threading")
    monkeypatch.setitem(
        sys.modules,
        "eventlet.patcher",
        _fake_patcher({"thread"}, originals={"threading": sentinel, "queue": sentinel}),
    )
    assert runtime.original("threading") is sentinel
    assert runtime.original("queue") is sentinel
    # time is not patched, so the stdlib module is already the original.
    import time

    assert runtime.original("time") is time


# --- worker registration ----------------------------------------------------


def _fake_worker(module_name: str, threads=64, class_str="gthread"):
    cls = type("FakeWorker", (), {})
    cls.__module__ = module_name
    worker = cls()
    worker.cfg = types.SimpleNamespace(
        worker_class_str=class_str, threads=threads, workers=1, graceful_timeout=30
    )
    return worker


def test_a_registered_gthread_worker_is_the_answer(clean_runtime):
    worker = _fake_worker("gunicorn.workers.gthread")
    runtime.register_gunicorn_worker(worker)
    assert runtime.worker_class() == "gthread"
    assert runtime.gthread_active() is True
    assert runtime.under_gunicorn() is True
    assert runtime.configured_threads() == 64
    info = runtime.registered_worker()
    assert info["graceful_timeout"] == 30 and info["workers"] == 1


def test_a_registered_eventlet_worker_has_no_thread_budget(clean_runtime):
    runtime.register_gunicorn_worker(_fake_worker("gunicorn.workers.geventlet", threads=1))
    assert runtime.worker_class() == "eventlet"
    assert runtime.gthread_active() is False
    assert runtime.configured_threads() is None


def test_an_unknown_worker_class_is_named_from_its_config(clean_runtime):
    runtime.register_gunicorn_worker(
        _fake_worker("some.custom.workers", class_str="mypkg.workers.FancyWorker")
    )
    assert runtime.worker_class() == "fancyworker"


def test_configured_threads_never_invents_a_number(clean_runtime, monkeypatch):
    # Dev server: no pool, whatever the environment says.
    monkeypatch.setenv("OPENALGO_EFFECTIVE_THREADS", "64")
    if runtime.worker_class() == "dev":
        assert runtime.configured_threads() is None
    # gthread without a registered worker: the launcher's export is used.
    monkeypatch.setattr(runtime, "worker_class", lambda: "gthread")
    assert runtime.configured_threads() == 64
    monkeypatch.setenv("OPENALGO_EFFECTIVE_THREADS", "not-a-number")
    assert runtime.configured_threads() is None
    monkeypatch.delenv("OPENALGO_EFFECTIVE_THREADS")
    assert runtime.configured_threads() is None


def test_requested_worker_class_defaults_to_eventlet(clean_runtime, monkeypatch):
    assert runtime.requested_worker_class() == "eventlet"
    monkeypatch.setenv("OPENALGO_WORKER_CLASS", "'gthread'")
    assert runtime.requested_worker_class() == "gthread"
    monkeypatch.setenv("OPENALGO_WORKER_CLASS", "something-else")
    assert runtime.requested_worker_class() == "eventlet"


def test_launcher_info_is_absent_without_the_launcher(clean_runtime, monkeypatch):
    monkeypatch.delenv("OPENALGO_LAUNCHER_VERSION", raising=False)
    assert runtime.launcher_info() is None
    monkeypatch.setenv("OPENALGO_LAUNCHER_VERSION", "1")
    monkeypatch.setenv("OPENALGO_REQUESTED_WORKER_CLASS", "gthread")
    monkeypatch.setenv("OPENALGO_EFFECTIVE_WORKER_CLASS", "gthread")
    monkeypatch.setenv("OPENALGO_EFFECTIVE_THREADS", "64")
    assert runtime.launcher_info() == {
        "version": "1",
        "requested": "gthread",
        "effective": "gthread",
        "threads": 64,
    }


def test_pool_stats_read_the_registered_worker_best_effort(clean_runtime):
    worker = _fake_worker("gunicorn.workers.gthread")
    worker.tpool = types.SimpleNamespace(
        _threads={1, 2, 3}, _work_queue=types.SimpleNamespace(qsize=lambda: 4)
    )
    worker.futures = [object(), object()]
    worker.nr_conns = 7
    runtime.register_gunicorn_worker(worker)
    assert runtime.gthread_pool_stats() == {
        "spawned": 3,
        "busy": 2,
        "waiting": 4,
        "open_connections": 7,
    }
    # A gunicorn that renamed one attribute costs that figure only.
    del worker.nr_conns
    assert runtime.gthread_pool_stats()["open_connections"] is None


def test_the_telegram_start_path_is_the_one_each_runtime_took_before(clean_runtime, monkeypatch):
    """The Telegram start path does not change on any existing runtime.

    It used to follow ``"eventlet" in sys.modules``. On a development server
    whose environment holds eventlet (every install.sh server) that was True by
    the first request, because the websocket proxy's startup probe imported
    eventlet to ask whether it was active, so the synchronous path ran there.
    The probe no longer imports eventlet, and asking only "is it patched" moved
    that server onto the asyncio path, which answers a network failure with a
    refusal instead of storing the token and retrying.
    """
    import services.telegram_bot_service as tg

    monkeypatch.delitem(sys.modules, "eventlet.patcher", raising=False)

    # Development server with eventlet installed: synchronous, as before.
    monkeypatch.setattr(tg, "_eventlet_installed", lambda: True)
    assert runtime.worker_class() == "dev"
    assert tg.use_sync_initialization() is True

    # Development server without eventlet (Windows): asyncio, as before.
    monkeypatch.setattr(tg, "_eventlet_installed", lambda: False)
    assert tg.use_sync_initialization() is False

    # The eventlet worker: synchronous, as before.
    monkeypatch.setitem(sys.modules, "eventlet.patcher", _fake_patcher({"thread", "socket"}))
    assert tg.use_sync_initialization() is True

    # The gthread worker runs the bot on real threads: asyncio, whatever is installed.
    monkeypatch.delitem(sys.modules, "eventlet.patcher")
    monkeypatch.setattr(runtime, "_patched", set())
    monkeypatch.setattr(tg, "_eventlet_installed", lambda: True)
    runtime.register_gunicorn_worker(_fake_worker("gunicorn.workers.gthread"))
    assert tg.use_sync_initialization() is False


def test_whether_eventlet_is_installed_is_answered_without_importing_it(tmp_path):
    result = _run_child(
        tmp_path,
        """
        import sys
        import services.telegram_bot_service as tg

        from importlib.util import find_spec

        assert tg._eventlet_installed() is (find_spec("eventlet") is not None)
        assert "eventlet" not in sys.modules
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


# --- subprocess proofs --------------------------------------------------------


def test_every_foundation_module_imports_cleanly_without_importing_eventlet(tmp_path):
    """Windows smoke as well: no eventlet, no fcntl, no POSIX-only signals."""
    result = _run_child(
        tmp_path,
        f"""
        import importlib, sys
        for name in {FOUNDATION_MODULES!r}:
            importlib.import_module(name)
        assert "eventlet" not in sys.modules, "a foundation module imported eventlet"
        assert "fcntl" not in sys.modules or sys.platform != "win32"
        from utils import runtime, real_threading
        import threading
        assert runtime.is_monkey_patched() is False
        assert runtime.worker_class() == "dev", runtime.worker_class()
        assert real_threading.Lock is threading.Lock
        assert real_threading._threading is threading
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


def test_swept_guards_never_import_eventlet(tmp_path):
    """Importing every swept module leaves eventlet out of sys.modules.

    Before the sweep, websocket_proxy.app_integration and the flattrade,
    definedge, shoonya and zebu data modules imported eventlet.patcher just to
    ask, which is what flipped every later guard under gthread.
    """
    modules = [name for name, _ in GUARDED_THREADING_ATTRS] + USE_ASYNC_MODULES
    result = _run_child(
        tmp_path,
        f"""
        import importlib, sys, threading
        for name in {modules!r}:
            importlib.import_module(name)
        assert "eventlet" not in sys.modules, sorted(m for m in sys.modules if "eventlet" in m)
        import blueprints.admin as admin
        admin._runtime_info()
        assert "eventlet" not in sys.modules, "the admin runtime report imported eventlet"
        for name, attr in {GUARDED_THREADING_ATTRS!r}:
            assert getattr(sys.modules[name], attr) is threading, (name, attr)
        for name in {USE_ASYNC_MODULES!r}:
            assert sys.modules[name].USE_ASYNC is True, name
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


def test_a_stub_eventlet_that_was_never_patched_changes_no_branch(tmp_path):
    """eventlet imported but not patched: every guard takes the stdlib branch.

    The stub's ``original()`` raises, so any module still asking eventlet for an
    original on an unpatched interpreter fails this test. Runs everywhere,
    including Windows, because the stub needs no real eventlet.
    """
    modules = [name for name, _ in GUARDED_THREADING_ATTRS] + USE_ASYNC_MODULES
    result = _run_child(
        tmp_path,
        f"""
        import importlib, sys, threading, time, types

        eventlet = types.ModuleType("eventlet")
        patcher = types.ModuleType("eventlet.patcher")
        patcher.is_monkey_patched = lambda name: False

        def original(name):
            raise AssertionError("original(%r) called on an unpatched process" % name)

        patcher.original = original
        eventlet.patcher = patcher
        sys.modules["eventlet"] = eventlet
        sys.modules["eventlet.patcher"] = patcher

        for name in {modules!r}:
            importlib.import_module(name)
        import services.agent.chatgpt_oauth as oauth
        from utils import real_threading, runtime

        assert runtime.is_monkey_patched() is False
        assert real_threading.Lock is threading.Lock
        assert oauth._real_sleep is time.sleep
        for name, attr in {GUARDED_THREADING_ATTRS!r}:
            assert getattr(sys.modules[name], attr) is threading, (name, attr)
        for name in {USE_ASYNC_MODULES!r}:
            assert sys.modules[name].USE_ASYNC is True, name
        assert "__original_module_threading" not in sys.modules
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


@pytest.mark.skipif(not _eventlet_installed(), reason="eventlet is not installed (Windows dev)")
def test_under_a_real_monkey_patch_every_guard_takes_the_eventlet_branch(tmp_path):
    """The branch each guard took before the sweep, under gunicorn+eventlet.

    Before: ``"eventlet" in sys.modules`` was True, so each guard used
    ``eventlet.patcher.original("threading")`` (or ``"time"``), and the four
    broker data modules set USE_ASYNC False. After: the same objects.
    """
    modules = [name for name, _ in GUARDED_THREADING_ATTRS] + USE_ASYNC_MODULES
    result = _run_child(
        tmp_path,
        f"""
        import eventlet
        eventlet.monkey_patch()

        import importlib, sys
        import eventlet.patcher as patcher

        from utils import runtime, real_threading

        assert runtime.is_monkey_patched() is True
        assert runtime.is_monkey_patched("socket") is True
        assert runtime.worker_class() == "eventlet"
        assert runtime.configured_threads() is None

        original_threading = patcher.original("threading")
        assert real_threading._threading is original_threading
        assert real_threading.Lock is original_threading.Lock
        assert real_threading.sleep is patcher.original("time").sleep

        for name in {modules!r}:
            importlib.import_module(name)
        for name, attr in {GUARDED_THREADING_ATTRS!r}:
            assert getattr(sys.modules[name], attr) is original_threading, (name, attr)
        for name in {USE_ASYNC_MODULES!r}:
            assert sys.modules[name].USE_ASYNC is False, name

        import services.agent.chatgpt_oauth as oauth
        assert oauth._real_sleep is patcher.original("time").sleep

        import websocket_proxy.app_integration as integration
        assert integration._eventlet_active() is True

        import blueprints.admin as admin
        info = admin._runtime_info()
        assert info["eventlet_active"] is True and info["wsgi_hint"] == "gunicorn-eventlet"

        from services.telegram_bot_service import use_sync_initialization
        assert use_sync_initialization() is True  # the Telegram and app.py guards
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


@pytest.mark.skipif(not _eventlet_installed(), reason="eventlet is not installed (Windows dev)")
def test_a_real_eventlet_imported_without_patching_changes_no_branch(tmp_path):
    """The gthread case: eventlet installed and imported, nothing patched."""
    modules = [name for name, _ in GUARDED_THREADING_ATTRS] + USE_ASYNC_MODULES
    result = _run_child(
        tmp_path,
        f"""
        import eventlet  # imported, never patched
        import importlib, sys, threading, time

        from utils import runtime, real_threading
        assert runtime.is_monkey_patched() is False
        assert runtime.worker_class() == "dev"
        assert real_threading.Lock is threading.Lock

        for name in {modules!r}:
            importlib.import_module(name)
        for name, attr in {GUARDED_THREADING_ATTRS!r}:
            assert getattr(sys.modules[name], attr) is threading, (name, attr)
        for name in {USE_ASYNC_MODULES!r}:
            assert sys.modules[name].USE_ASYNC is True, name
        import services.agent.chatgpt_oauth as oauth
        assert oauth._real_sleep is time.sleep
        # Not asserted here: "__original_module_threading" absent. Importing
        # eventlet builds that copy itself (eventlet.hubs asks its patcher for
        # the original threading module), which is why nothing in the app may
        # import eventlet merely to ask whether it is active.
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


# --- tripwire -----------------------------------------------------------------


def _tracked_python_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
        files = [REPO / line for line in out.splitlines() if line]
    except (OSError, subprocess.SubprocessError):
        files = list(REPO.rglob("*.py"))
    skip_parts = {"test", ".venv", "node_modules", "frontend", ".git"}
    return [
        path
        for path in files
        if path.exists() and not (skip_parts & set(path.relative_to(REPO).parts))
    ]


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _eventlet_guard_sites(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            left = node.left
            if (
                isinstance(left, ast.Constant)
                and isinstance(left.value, str)
                and left.value.startswith("eventlet")
                and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
                and any(
                    isinstance(c, ast.Attribute) and c.attr == "modules" for c in node.comparators
                )
            ):
                sites.append(f"{_label(path)}:{node.lineno} eventlet in sys.modules")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "eventlet" or alias.name.startswith("eventlet."):
                    sites.append(f"{_label(path)}:{node.lineno} import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "eventlet" or node.module.startswith("eventlet.")):
                sites.append(f"{_label(path)}:{node.lineno} from {node.module}")
    return sites


def test_no_production_module_guards_on_import_state_or_imports_eventlet():
    """Every eventlet question goes through utils.runtime.

    ``"eventlet" in sys.modules`` answers the wrong question, and importing
    eventlet to ask the right one changes the answer for everyone after.
    """
    sites = []
    for path in _tracked_python_files():
        sites.extend(_eventlet_guard_sites(path))
    assert sites == [], "eventlet guards outside utils.runtime:\n" + "\n".join(sites)


def test_the_tripwire_recognises_both_patterns(tmp_path):
    """So the scan above cannot pass because it matches nothing."""
    sample = tmp_path / "probe.py"
    sample.write_text(
        'import sys\nif "eventlet" in sys.modules:\n    import eventlet.patcher\n'
        "from eventlet import patcher\n",
        encoding="utf-8",
    )
    found = _eventlet_guard_sites(sample)
    assert len(found) == 3, found
