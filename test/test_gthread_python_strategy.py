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

import threading

import pytest

from blueprints import python_strategy as ps


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
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or node.lineno in guarded:
            continue
        it = node.iter
        base = it.func.value if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) else it
        if isinstance(base, ast.Name) and base.id in REGISTRIES:
            offenders.append(f"line {node.lineno} iterates {base.id}")
    assert offenders == [], (
        "iterate a snapshot, not the live registry -- use "
        f"snapshot_strategy_configs(): {offenders}"
    )
