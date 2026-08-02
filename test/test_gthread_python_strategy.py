"""The /python strategy host under real threads (GT-A14-*).

The Python Strategy Host keeps two module-level registries -- STRATEGY_CONFIGS
(saved strategies) and RUNNING_STRATEGIES (live subprocesses) -- and reaches
them from request handlers, the APScheduler jobs that start and stop strategies
on IST times, and a cleanup sweep. Under gthread those run on real threads
concurrently.

103 references, only 38 of them inside PROCESS_LOCK. The migration had covered
exactly one row here (the scheduler's misfire_grace_time), because the
check-then-act gate only recognised attribute guards like `self.foo` and is
blind to bare module-level names.

Two shapes are actually dangerous:

1. Iterating a registry while another thread adds or removes a strategy.
   `RuntimeError: dictionary changed size during iteration`. The listing loop
   is the worst case because its body does file I/O (`save_configs()`) and a
   process poll, so it holds the iteration open for a long time.

2. Membership-test followed by indexing. `KeyError`. The window is widest where
   the guard lives in `validate_strategy_access()` and the indexing happens
   back in the caller.

Neither is reachable under eventlet, which never yields between the two
statements. Both are reachable on real threads -- including on Windows and
macOS today, whose dev server has always used threads.
"""

import os
import threading
from pathlib import Path
from unittest import mock

import pytest

from blueprints import python_strategy as ps

_ENV_PROBE_FILE = Path(__file__).resolve().parent / "_env_probe_strategy.py"


@pytest.fixture(autouse=True)
def clean_registries():
    """Never mutate the real module state across tests."""
    saved_cfg = dict(ps.STRATEGY_CONFIGS)
    saved_run = dict(ps.RUNNING_STRATEGIES)
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()
    yield
    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(saved_cfg)
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(saved_run)


def _cfg(i):
    return {"name": f"s{i}", "file_path": f"/tmp/s{i}.py", "user_id": "u1"}


# ---------------------------------------------------------------------------
# The safe accessors
# ---------------------------------------------------------------------------


def test_get_config_returns_none_instead_of_raising():
    ps.STRATEGY_CONFIGS["a"] = _cfg(1)
    assert ps.get_strategy_config("a")["name"] == "s1"
    assert ps.get_strategy_config("missing") is None


def test_get_running_returns_none_instead_of_raising():
    ps.RUNNING_STRATEGIES["a"] = {"started_at": "now", "log_file": "/tmp/a.log"}
    assert ps.get_running_strategy("a")["log_file"] == "/tmp/a.log"
    assert ps.get_running_strategy("missing") is None


def test_snapshot_is_a_copy_not_a_live_view():
    """The listing loop iterates this while other threads mutate the registry,
    so it must not be a view onto the live dict."""
    ps.STRATEGY_CONFIGS["a"] = _cfg(1)
    snap = ps.snapshot_strategy_configs()
    ps.STRATEGY_CONFIGS["b"] = _cfg(2)
    assert [sid for sid, _ in snap] == ["a"], "snapshot tracked a later insert"


def test_snapshot_survives_concurrent_mutation():
    """The RuntimeError reproduction: iterate while another thread churns."""
    for i in range(200):
        ps.STRATEGY_CONFIGS[f"s{i}"] = _cfg(i)

    stop = threading.Event()
    errors = []

    def churn():
        i = 0
        while not stop.is_set():
            ps.STRATEGY_CONFIGS[f"new{i}"] = _cfg(i)
            ps.STRATEGY_CONFIGS.pop(f"new{i}", None)
            i += 1

    def lister():
        while not stop.is_set():
            try:
                for _sid, cfg in ps.snapshot_strategy_configs():
                    _ = cfg.get("name")  # stands in for the loop body's work
            except Exception as exc:  # noqa: BLE001 - recording is the point
                errors.append(f"{type(exc).__name__}: {exc}")
                return

    threads = [threading.Thread(target=churn)] + [
        threading.Thread(target=lister) for _ in range(3)
    ]
    for t in threads:
        t.start()
    stop.wait(2.0)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"listing raised while the registry changed: {errors[:3]}"


def test_lookups_survive_concurrent_removal():
    """The KeyError reproduction: look up while another thread deletes."""
    stop = threading.Event()
    errors = []

    def churn():
        i = 0
        while not stop.is_set():
            ps.STRATEGY_CONFIGS["hot"] = _cfg(i)
            ps.RUNNING_STRATEGIES["hot"] = {"started_at": "t", "log_file": "f"}
            ps.STRATEGY_CONFIGS.pop("hot", None)
            ps.RUNNING_STRATEGIES.pop("hot", None)
            i += 1

    def reader():
        while not stop.is_set():
            try:
                ps.get_strategy_config("hot")
                ps.get_running_strategy("hot")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
                return

    threads = [threading.Thread(target=churn)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    stop.wait(2.0)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"lookup raised during removal: {errors[:3]}"


# ---------------------------------------------------------------------------
# Structural: the unsafe shapes must not come back
# ---------------------------------------------------------------------------


REGISTRIES = {"STRATEGY_CONFIGS", "RUNNING_STRATEGIES"}


def _module_tree():
    import ast
    import inspect

    return ast.parse(inspect.getsource(ps)), ast


def _lock_guarded_lines(tree, ast):
    """Lines inside a `with PROCESS_LOCK:` block.

    Guard and index under the *same* held lock is safe and is the existing
    pattern in the start/stop/delete paths. Flagging those would be a false
    positive and would push churn into the most delicate code in the file.
    """
    covered = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        text = " ".join(ast.dump(i.context_expr) for i in node.items)
        if "PROCESS_LOCK" not in text:
            continue
        for sub in ast.walk(node):
            if hasattr(sub, "lineno"):
                covered.add(sub.lineno)
    return covered


def test_no_membership_test_then_index_on_a_registry():
    """`if sid in D:` followed by `D[sid]` is a KeyError waiting for a thread
    switch. Use the accessors instead."""
    tree, ast = _module_tree()
    guarded = _lock_guarded_lines(tree, ast)

    offenders = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            guarded_names = {
                c.id
                for cmp in ast.walk(node.test) if isinstance(cmp, ast.Compare)
                for op in cmp.ops if isinstance(op, (ast.In, ast.NotIn))
                for c in ast.walk(cmp) if isinstance(c, ast.Name) and c.id in REGISTRIES
            }
            if not guarded_names:
                continue
            # An index of the same registry anywhere in the same function body
            for sub in ast.walk(fn):
                if (
                    isinstance(sub, ast.Subscript)
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id in guarded_names
                    and not isinstance(sub.ctx, ast.Store)
                    and sub.lineno not in guarded
                ):
                    offenders.append(f"{fn.name}:{sub.lineno} indexes {sub.value.id}")
    assert offenders == [], (
        "membership-test-then-index on a registry can raise KeyError under "
        f"threads; use get_strategy_config/get_running_strategy: {sorted(set(offenders))}"
    )


def test_no_direct_iteration_of_a_registry():
    """`for x in STRATEGY_CONFIGS.items()` can raise RuntimeError mid-loop."""
    tree, ast = _module_tree()
    guarded = _lock_guarded_lines(tree, ast)

    offenders = []
    # ast.For AND ast.comprehension: the first version of this check looked only
    # at For nodes, so a list comprehension in /python/status kept iterating the
    # live registry while all seven tests passed. A blind spot in the check is
    # indistinguishable from a clean file.
    iterables = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and node.lineno not in guarded:
            iterables.append((node.lineno, node.iter))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if node.lineno in guarded:
                continue
            for gen in node.generators:
                iterables.append((node.lineno, gen.iter))

    for lineno, it in iterables:
        base = it.func.value if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) else it
        if isinstance(base, ast.Name) and base.id in REGISTRIES:
            offenders.append(f"line {lineno} iterates {base.id}")
    assert offenders == [], (
        "iterate a snapshot, not the live registry -- use "
        f"snapshot_strategy_configs(): {offenders}"
    )


# ---------------------------------------------------------------------------
# Subprocess launch, config persistence, lifecycle (external audit, 2026-08-02)
# ---------------------------------------------------------------------------


def test_no_preexec_fn_anywhere():
    """preexec_fn runs between fork and exec. The Python docs: "not safe to use
    in the presence of threads. The child process could deadlock before exec is
    called." Ours called logger.debug()/logger.warning(), and logging takes
    locks -- a fork while another thread held one produced a child that hung
    forever, before the strategy ever started.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ps))
    # Only a real keyword argument or subscript assignment counts -- prose in a
    # comment or docstring explaining why it was removed must not fail this.
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "preexec_fn":
            offenders.append(f"keyword at line {node.value.lineno}")
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "preexec_fn"
            and isinstance(node.ctx, ast.Store)
        ):
            offenders.append(f"assignment at line {node.lineno}")
    assert offenders == [], (
        f"preexec_fn is back ({offenders}); "
        "apply limits post-exec via _RLIMIT_BOOTSTRAP"
    )


def test_bootstrap_runs_the_script_as_main_with_limits(tmp_path):
    """The replacement must preserve __main__, __file__ and argv, or every
    `if __name__ == "__main__":` strategy silently stops running."""
    import subprocess
    import sys

    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, sys, resource\n"
        "print('NAME', __name__)\n"
        "print('FILE', os.path.basename(__file__))\n"
        "print('ARGV0', os.path.basename(sys.argv[0]))\n"
        "print('CPU', resource.getrlimit(resource.RLIMIT_CPU)[0])\n"
    )
    env = dict(os.environ)
    env["OPENALGO_STRATEGY_MEM_MB"] = "512"
    env["OPENALGO_STRATEGY_CPU_SEC"] = "1234"

    out = subprocess.run(
        [sys.executable, "-u", "-c", ps._RLIMIT_BOOTSTRAP, str(probe)],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert out.returncode == 0, out.stderr
    assert "NAME __main__" in out.stdout
    assert "FILE probe.py" in out.stdout
    assert "ARGV0 probe.py" in out.stdout
    # RLIMIT_AS is refused on macOS; RLIMIT_CPU works everywhere we run.
    assert "CPU 1234" in out.stdout, f"CPU limit not applied: {out.stdout}"


def test_concurrent_saves_never_corrupt_the_config(tmp_path, monkeypatch):
    """Two savers previously shared ONE temp path, so their writes interleaved
    in the same file and whichever renamed second published the other's partial
    JSON. Every read must parse."""
    import json as _json
    import threading as _th

    cfg = tmp_path / "strategies.json"
    monkeypatch.setattr(ps, "CONFIG_FILE", cfg)

    for i in range(150):
        ps.STRATEGY_CONFIGS[f"s{i}"] = _cfg(i)

    errors = []
    stop = _th.Event()

    def saver():
        while not stop.is_set():
            try:
                ps.save_configs()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"save: {type(exc).__name__}: {exc}")
                return

    def reader():
        while not stop.is_set():
            try:
                if cfg.exists():
                    _json.loads(cfg.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"read: {type(exc).__name__}: {exc}")
                return

    threads = [_th.Thread(target=saver) for _ in range(4)] + [
        _th.Thread(target=reader) for _ in range(2)
    ]
    for t in threads:
        t.start()
    stop.wait(2.0)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"concurrent saves corrupted the config: {errors[:3]}"
    # No temp files left behind next to the config on a long-lived worker.
    leftovers = [p.name for p in tmp_path.glob("*.tmp")]
    assert leftovers == [], f"temp files leaked: {leftovers}"


def test_initialization_is_single_flight_and_marks_done_last():
    """The flag used to be set before restoration ran, so a second thread
    returned immediately and served half-restored state."""
    import inspect

    src = inspect.getsource(ps.initialize_with_app_context)
    assert "_INIT_LOCK" in src, "initialization is not serialized"

    body = inspect.getsource(ps._initialize_locked)
    set_true = body.index("_initialized = True")
    assert "restore_strategy_states()" in body
    assert body.index("restore_strategy_states()") < set_true, (
        "the flag is still set before restoration finishes"
    )


def test_shutdown_does_not_hold_the_lock_across_process_waits():
    """stop_strategy_process() terminates and waits. Doing that under
    PROCESS_LOCK blocked every other thread for the whole shutdown, and the
    sequential waits could outrun Gunicorn's 30s graceful timeout."""
    import ast
    import inspect
    import textwrap

    fn = ast.parse(textwrap.dedent(inspect.getsource(ps.cleanup_on_exit))).body[0]

    # Structural, not textual: a comment mentioning stop_strategy_process must
    # not decide this. Find calls that are lexically inside a `with
    # PROCESS_LOCK:` block.
    locked_lines = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.With) and "PROCESS_LOCK" in ast.dump(node):
            for sub in ast.walk(node):
                if hasattr(sub, "lineno"):
                    locked_lines.add(sub.lineno)

    inside = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "stop_strategy_process"
        and node.lineno in locked_lines
    ]
    assert inside == [], (
        f"stop_strategy_process is called while holding PROCESS_LOCK (lines {inside}); "
        "it terminates and waits for a child, which blocks every other thread"
    )
    assert ps._SHUTDOWN_BUDGET_SECONDS < 30, (
        "the shutdown budget must stay inside gunicorn's --graceful-timeout 30"
    )


# ---------------------------------------------------------------------------
# Second audit round (2026-08-02): the fixes above were themselves broken
# ---------------------------------------------------------------------------


def test_limits_survive_the_env_replacement():
    """start_strategy_process() builds its own env and assigns it wholesale, so
    anything set in subprocess_args earlier was silently discarded and every
    strategy ran with NO limits. The values must be applied to the final env."""
    import inspect

    # Capture what Popen is ACTUALLY given, rather than reading the source --
    # a textual check here passed while the env was being discarded downstream.
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            captured["env"] = kw.get("env")
            self.pid = 424242

        def poll(self):
            return None

    ps.STRATEGY_CONFIGS["envprobe"] = dict(
        _cfg(1), file_path=str(_ENV_PROBE_FILE), file_name=_ENV_PROBE_FILE.name
    )
    # The start path consults the database for the active broker and for master
    # contract readiness; neither exists in a unit-test DB, so stub them. The
    # point here is what reaches Popen, not the preconditions.
    with mock.patch.object(ps.subprocess, "Popen", _FakePopen), \
         mock.patch.object(ps, "get_active_broker", lambda: "zerodha"), \
         mock.patch.object(ps, "check_master_contract_ready", lambda *a, **k: (True, "ready")):
        result = ps.start_strategy_process("envprobe")
    ps.RUNNING_STRATEGIES.pop("envprobe", None)

    ok = result[0] if isinstance(result, tuple) else result
    assert ok, f"the strategy did not start, so nothing reached Popen: {result}"
    env = captured.get("env")
    assert env is not None, f"Popen was never given an env (captured={captured})"
    assert env.get("OPENALGO_STRATEGY_MEM_MB") == str(ps.STRATEGY_MEMORY_LIMIT_MB), (
        "the limits do not reach the process Popen actually launches: "
        f"{ {k: v for k, v in env.items() if k.startswith('OPENALGO_STRATEGY')} }"
    )
    assert env.get("OPENALGO_STRATEGY_CPU_SEC") == str(ps.STRATEGY_CPU_TIME_LIMIT_SEC)
    assert env.get("OPENALGO_STRATEGY_NOFILE") == str(ps.STRATEGY_NOFILE_LIMIT)
    assert env.get("OPENALGO_STRATEGY_NPROC") == str(ps.STRATEGY_NPROC_LIMIT)

    env = ps.apply_strategy_limits_env({})
    assert env["OPENALGO_STRATEGY_MEM_MB"] == str(ps.STRATEGY_MEMORY_LIMIT_MB)
    assert env["OPENALGO_STRATEGY_CPU_SEC"] == str(ps.STRATEGY_CPU_TIME_LIMIT_SEC)
    assert int(env["OPENALGO_STRATEGY_NOFILE"]) > 0
    assert int(env["OPENALGO_STRATEGY_NPROC"]) > 0

    # And the arg builder must NOT set env, or it re-creates the illusion.
    # Structural, so the comment explaining why it must not is not itself a hit.
    import ast
    import textwrap

    fn = ast.parse(textwrap.dedent(inspect.getsource(ps.create_subprocess_args))).body[0]
    sets_env = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Subscript)
        and isinstance(n.ctx, ast.Store)
        and isinstance(n.slice, ast.Constant)
        and n.slice.value == "env"
    ]
    assert sets_env == [], (
        f"create_subprocess_args assigns env (lines {sets_env}); "
        "it will be discarded when start_strategy_process replaces it"
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX bootstrap")
def test_bootstrap_preserves_sibling_imports(tmp_path):
    """`python script.py` puts the script's directory on sys.path[0]; runpy does
    not. A strategy importing a sibling helper worked before and would raise
    ModuleNotFoundError after the change -- a silent break on upgrade."""
    import subprocess
    import sys

    (tmp_path / "helper.py").write_text("VALUE = 'sibling-ok'\n")
    strat = tmp_path / "strat.py"
    strat.write_text(
        "import sys\n"
        "from helper import VALUE\n"
        "print('IMPORT', VALUE)\n"
        "print('PATH0', sys.path[0])\n"
    )

    out = subprocess.run(
        [sys.executable, "-u", "-c", ps._RLIMIT_BOOTSTRAP, str(strat)],
        capture_output=True, text=True, timeout=60,
        env=ps.apply_strategy_limits_env(dict(os.environ)),
    )
    assert out.returncode == 0, f"sibling import failed: {out.stderr[-400:]}"
    assert "IMPORT sibling-ok" in out.stdout
    assert str(tmp_path) in out.stdout, f"sys.path[0] not the strategy dir: {out.stdout}"


def test_save_configs_lock_order_cannot_deadlock():
    """save_configs took _CONFIG_FILE_LOCK then PROCESS_LOCK, while six callers
    already held PROCESS_LOCK when calling it. Opposing order between two
    threads is an ABBA deadlock that hangs the worker permanently.

    The previous concurrent-save test only ever exercised one order, so it
    passed against a deadlocking implementation.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ps))
    nested = []
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and "_CONFIG_FILE_LOCK" in ast.dump(node):
            for sub in ast.walk(node):
                if sub is not node and isinstance(sub, ast.With) and "LOCK" in ast.dump(sub):
                    nested.append(sub.lineno)
    assert nested == [], (
        f"a lock is acquired inside _CONFIG_FILE_LOCK (lines {nested}); "
        "PROCESS_LOCK must always be taken first and released before it"
    )


def test_save_configs_deadlocks_under_opposing_order(tmp_path, monkeypatch):
    """The behavioural half: one thread saves standalone while another saves
    while already holding PROCESS_LOCK, exactly as start/stop/delete do."""
    import threading as _th

    cfg = tmp_path / "s.json"
    monkeypatch.setattr(ps, "CONFIG_FILE", cfg)
    for i in range(40):
        ps.STRATEGY_CONFIGS[f"s{i}"] = _cfg(i)

    done = _th.Event()
    errors = []

    def standalone():
        for _ in range(120):
            if not ps.save_configs():
                errors.append("save returned False")
                return

    def holding_process_lock():
        for _ in range(120):
            with ps.PROCESS_LOCK:          # the order start/stop/delete use
                if not ps.save_configs():
                    errors.append("save returned False (locked path)")
                    return

    threads = [_th.Thread(target=standalone) for _ in range(3)] + [
        _th.Thread(target=holding_process_lock) for _ in range(3)
    ]
    for t in threads:
        t.start()

    def waiter():
        for t in threads:
            t.join(timeout=30)
        done.set()

    w = _th.Thread(target=waiter, daemon=True)
    w.start()
    assert done.wait(45), (
        "save_configs deadlocked under opposing lock order -- threads still alive: "
        f"{[t.name for t in threads if t.is_alive()]}"
    )
    assert errors == [], errors


def test_save_configs_reports_failure():
    """A caller that just changed state needs to know the change never reached
    disk. It used to swallow every exception and return None."""
    import inspect

    assert "-> bool" in inspect.getsource(ps.save_configs).splitlines()[0]


def test_shutdown_stops_the_scheduler_and_kills_survivors():
    """Children are reparented to init on bare metal, not killed with the
    worker: a strategy left running keeps a broker session and can place orders
    with nothing supervising it. And a live scheduler can start a new strategy
    behind the cleanup."""
    import ast
    import inspect
    import textwrap

    src = inspect.getsource(ps.cleanup_on_exit)
    fn = ast.parse(textwrap.dedent(src)).body[0]

    # Structural: a comment mentioning killpg must not satisfy this. A textual
    # check here passed against an implementation that had had the call removed.
    calls = {
        ast.unparse(n.func)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert any(c.endswith("SCHEDULER.shutdown") or c.endswith("shutdown") for c in calls), (
        f"the scheduler is never shut down during cleanup (calls: {sorted(calls)})"
    )
    assert "os.killpg" in calls, (
        f"surviving process groups are never killed (calls: {sorted(calls)})"
    )

    # Scheduler shutdown must come before the stopping loop.
    assert src.index("SCHEDULER.shutdown") < src.index("stop_strategy_process("), (
        "the scheduler is stopped after strategies, so it can start new ones"
    )

    # And still no waiting under the lock.
    locked = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.With) and "PROCESS_LOCK" in ast.dump(node):
            for sub in ast.walk(node):
                if hasattr(sub, "lineno"):
                    locked.add(sub.lineno)
    inside = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "stop_strategy_process"
        and n.lineno in locked
    ]
    assert inside == [], f"stop_strategy_process still called under PROCESS_LOCK: {inside}"


# ---------------------------------------------------------------------------
# Third audit round (2026-08-02)
# ---------------------------------------------------------------------------


def test_older_snapshot_cannot_overwrite_a_newer_one(tmp_path, monkeypatch):
    """Serialising under one lock and writing under another fixed the deadlock
    but not the ORDER: two savers could snapshot gen1, gen2 and reach the file
    lock as gen2, gen1, leaving stale state on disk while both returned True."""
    import json as _json
    import threading as _th

    cfg = tmp_path / "s.json"
    monkeypatch.setattr(ps, "CONFIG_FILE", cfg)
    monkeypatch.setattr(ps, "_CONFIG_GENERATION", 0)
    monkeypatch.setattr(ps, "_PERSISTED_GENERATION", 0)

    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS["k"] = {"generation": 1}

    reached = _th.Event()
    release = _th.Event()
    real_lock = ps._CONFIG_FILE_LOCK

    class _StallingLock:
        """Holds the FIRST writer at the door until the second has published,
        forcing the exact inversion by hand."""
        def __init__(self):
            self.first = True

        def __enter__(self):
            if self.first:
                self.first = False
                reached.set()
                release.wait(10)
            real_lock.acquire()
            return self

        def __exit__(self, *a):
            real_lock.release()
            return False

    monkeypatch.setattr(ps, "_CONFIG_FILE_LOCK", _StallingLock())

    results = {}

    def old_writer():
        results["old"] = ps.save_configs()          # snapshots generation 1

    t = _th.Thread(target=old_writer)
    t.start()
    assert reached.wait(10), "the first writer never reached the file lock"

    ps.STRATEGY_CONFIGS["k"] = {"generation": 2}
    results["new"] = ps.save_configs()              # snapshots and writes gen 2

    release.set()
    t.join(timeout=10)

    persisted = _json.loads(cfg.read_text(encoding="utf-8"))["k"]["generation"]
    assert persisted == 2, (
        f"an older snapshot overwrote a newer one: in-memory=2, persisted={persisted}"
    )
    assert results["old"] is True and results["new"] is True


def test_mutating_routes_report_persistence_failure():
    """A route that reports success after the save failed tells the user their
    change is safe when it will vanish on restart."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ps))
    routes = {
        "delete_strategy", "clear_error_state", "save_strategy",
        "new_strategy", "schedule_strategy_route",
    }
    unchecked = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if fn.name not in routes:
            continue
        checked = any(
            isinstance(n, ast.UnaryOp)
            and isinstance(n.operand, ast.Call)
            and getattr(n.operand.func, "id", "") == "save_configs"
            for n in ast.walk(fn)
        )
        if not checked:
            unchecked.append(fn.name)
    assert unchecked == [], (
        f"these routes ignore save_configs() failure and still report success: {unchecked}"
    )


def test_start_is_refused_once_shutdown_has_begun():
    """SCHEDULER.shutdown(wait=False) lets a running job finish, so a scheduled
    start could land after cleanup's snapshot -- never seen, never stopped, and
    outliving the worker."""
    import inspect

    assert "_SHUTTING_DOWN" in inspect.getsource(ps.start_strategy_process), (
        "start_strategy_process does not check the shutdown flag"
    )
    assert "_SHUTTING_DOWN" in inspect.getsource(ps.cleanup_on_exit)

    ps._SHUTTING_DOWN.set()
    try:
        ok, message = ps.start_strategy_process("anything")
        assert ok is False, "a strategy started during shutdown"
        assert "shutting down" in message.lower()
    finally:
        ps._SHUTTING_DOWN.clear()


def test_windows_survivors_get_tree_termination():
    """proc.kill() ends only the launcher; a strategy that spawned anything
    leaves the tree behind. taskkill /F /T is what the normal stop path uses."""
    import inspect

    src = inspect.getsource(ps.cleanup_on_exit)
    win = src[src.index("if IS_WINDOWS:"):]
    assert "taskkill" in win and "/T" in win, (
        "Windows survivors are not tree-terminated"
    )


def test_nproc_limit_matches_the_original():
    """256 was the value the original preexec_fn set. Lowering it silently is a
    compatibility change, not a fix."""
    assert ps.STRATEGY_NPROC_LIMIT == 256
    assert ps.STRATEGY_NOFILE_LIMIT == 256
