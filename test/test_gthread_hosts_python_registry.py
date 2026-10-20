"""The /python registries are iterated and changed only under PROCESS_LOCK (hosts-02).

Request handlers, the scheduler's jobs, the dead-process reaper and the startup
restore all walk STRATEGY_CONFIGS, and under eventlet none of those loops ever
yielded mid-iteration. Under the gthread worker they are real threads: an upload
landing while the strategies list was being built raised "dictionary changed
size during iteration", so the page answered 500, and the pending-start loop
aborted after it had already cleared the error flags, leaving strategies neither
started nor flagged.

The behavioural test drives the listing, the status route and the reaper
against threads creating and deleting strategies. The structural test holds the
module to the rule that fixes it: every loop over the registry, and every write
into it, sits inside ``with PROCESS_LOCK``.
"""

import ast
import inspect
import threading
import time

import pytest
from flask import Flask

from blueprints import python_strategy as ps


@pytest.fixture(autouse=True)
def clean_registries(monkeypatch):
    saved_configs = dict(ps.STRATEGY_CONFIGS)
    saved_running = dict(ps.RUNNING_STRATEGIES)
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()
    monkeypatch.setattr(ps, "save_configs", lambda: True)
    yield
    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(saved_configs)
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(saved_running)


def test_listing_and_reaping_survive_concurrent_create_and_delete(monkeypatch):
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda *a, **k: (True, "ready"))
    for i in range(50):
        ps.STRATEGY_CONFIGS[f"seed_{i}"] = {"name": f"seed_{i}", "exchange": "NSE"}

    app = Flask(__name__)
    errors = []
    stop = threading.Event()
    barrier = threading.Barrier(6)

    def reader(kind):
        barrier.wait()
        with app.test_request_context("/python/api/strategies"):
            while not stop.is_set():
                try:
                    if kind == "list":
                        ps.api_get_strategies.__wrapped__()
                    elif kind == "status":
                        ps.status.__wrapped__()
                    else:
                        ps.cleanup_dead_processes()
                except Exception as exc:  # the defect under test
                    errors.append(f"{kind}: {type(exc).__name__}: {exc}")
                    return

    def writer(prefix):
        barrier.wait()
        i = 0
        while not stop.is_set():
            sid = f"{prefix}_{i}"
            with ps.PROCESS_LOCK:
                ps.STRATEGY_CONFIGS[sid] = {"name": sid, "exchange": "NSE"}
            with ps.PROCESS_LOCK:
                ps.STRATEGY_CONFIGS.pop(sid, None)
            i += 1

    threads = [
        threading.Thread(target=reader, args=(k,)) for k in ("list", "status", "reap", "list")
    ]
    threads += [threading.Thread(target=writer, args=(p,)) for p in ("a", "b")]
    for t in threads:
        t.start()
    time.sleep(2)
    stop.set()
    for t in threads:
        t.join(10)

    assert errors == []


def _is_registry(node) -> bool:
    return isinstance(node, ast.Name) and node.id == "STRATEGY_CONFIGS"


def _touches_registry(node) -> bool:
    """STRATEGY_CONFIGS itself, a view of it, or an entry of it."""
    if _is_registry(node):
        return True
    if isinstance(node, ast.Subscript):
        return _touches_registry(node.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in ("items", "values", "keys") and _is_registry(node.func.value)
    return False


def _unlocked_registry_uses(tree):
    """Loops over, and writes into, STRATEGY_CONFIGS outside ``with PROCESS_LOCK``."""
    found = []

    def locked_by(node) -> bool:
        return any(
            isinstance(item.context_expr, ast.Name) and item.context_expr.id == "PROCESS_LOCK"
            for item in node.items
        )

    def visit(node, locked, function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
            locked = False
        if isinstance(node, ast.With) and locked_by(node):
            locked = True

        if not locked:
            if isinstance(node, (ast.For, ast.comprehension)) and _touches_registry(node.iter):
                found.append((function, getattr(node, "lineno", node.iter.lineno), "iterates"))
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.Delete):
                targets = node.targets
            for target in targets:
                if isinstance(target, ast.Subscript) and _touches_registry(target.value):
                    found.append((function, node.lineno, "writes"))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("pop", "update", "clear", "setdefault", "popitem")
                and (
                    _is_registry(node.func.value)
                    or isinstance(node.func.value, ast.Subscript)
                    and _touches_registry(node.func.value)
                )
            ):
                found.append((function, node.lineno, f"calls {node.func.attr}"))

        for child in ast.iter_child_nodes(node):
            visit(child, locked, function)

    visit(tree, False, "<module>")
    return found


def test_every_registry_loop_and_write_holds_process_lock():
    tree = ast.parse(inspect.getsource(ps))
    unlocked = _unlocked_registry_uses(tree)
    assert unlocked == [], (
        "STRATEGY_CONFIGS is iterated or written outside `with PROCESS_LOCK`: "
        f"{unlocked}. Iterate snapshot_strategy_configs() and write under the lock "
        "or through _update_config."
    )


def test_the_structural_check_sees_an_unlocked_loop():
    """The check above must be able to fail, or it proves nothing."""
    source = (
        "def f():\n"
        "    for sid, config in STRATEGY_CONFIGS.items():\n"
        "        STRATEGY_CONFIGS[sid]['x'] = 1\n"
        "    with PROCESS_LOCK:\n"
        "        for sid in STRATEGY_CONFIGS:\n"
        "            pass\n"
    )
    found = _unlocked_registry_uses(ast.parse(source))
    assert [(what) for _, _, what in found] == ["iterates", "writes"]
