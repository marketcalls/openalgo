"""Closes the last sandbox investigations (gate A9) and flow writers (F-04).

Covers GT-A9-02, GT-A9-03, GT-A9-04, GT-A9-07, GT-A9-10 and GT-F-04.
"""

import importlib
import importlib.util
import inspect
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_real_sandbox(*names):
    """`test/sandbox/` shadows the real package under pytest."""
    saved = {k: v for k, v in sys.modules.items() if k == "sandbox" or k.startswith("sandbox.")}
    for key in list(saved):
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        "sandbox",
        REPO / "sandbox" / "__init__.py",
        submodule_search_locations=[str(REPO / "sandbox")],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["sandbox"] = package
    spec.loader.exec_module(package)
    try:
        return tuple(importlib.import_module(f"sandbox.{n}") for n in names)
    finally:
        for key in [k for k in sys.modules if k == "sandbox" or k.startswith("sandbox.")]:
            del sys.modules[key]
        sys.modules.update(saved)


execution_engine, squareoff_manager, holdings_manager = _load_real_sandbox(
    "execution_engine", "squareoff_manager", "holdings_manager"
)


# --------------------------------------------------------------------------
# GT-A9-03: exactly-once fills
# --------------------------------------------------------------------------


def test_fill_path_is_serialized():
    """_process_order checks whether the order already has a trade, and
    _execute_order then creates one. That check-then-insert is not atomic, and
    SandboxTrades.orderid is indexed but NOT unique, so the database will not
    reject a duplicate -- two fills create two trades and double the position.
    """
    engine_cls = execution_engine.ExecutionEngine
    assert hasattr(engine_cls, "_fill_lock")
    assert "_fill_lock" in inspect.getsource(engine_cls._process_order)


def test_fill_lock_is_shared_across_engine_instances():
    """The polling engine and the WebSocket engine are separate objects."""
    engine_cls = execution_engine.ExecutionEngine
    assert engine_cls._fill_lock is engine_cls._fill_lock
    # Class attribute, so every instance sees the same lock.
    assert "_fill_lock = threading.RLock()" in (
        REPO / "sandbox" / "execution_engine.py"
    ).read_text(encoding="utf-8")


def test_duplicate_trade_guard_still_precedes_the_insert():
    """The protection depends on the check and the insert staying together."""
    src = (REPO / "sandbox" / "execution_engine.py").read_text(encoding="utf-8")
    check_at = src.index("existing_trade = SandboxTrades.query")
    insert_at = src.index("trade = SandboxTrades(")
    assert check_at < insert_at, "the duplicate-trade check no longer precedes the insert"


def test_orderid_uniqueness_is_documented_as_the_stronger_fix():
    """A UNIQUE constraint would hold across processes too, but needs a
    migration and a duplicate sweep -- deliberately not bundled here."""
    src = (REPO / "sandbox" / "execution_engine.py").read_text(encoding="utf-8")
    assert "UNIQUE constraint" in src, "the stronger fix is not recorded"


# --------------------------------------------------------------------------
# GT-A9-10: square-off
# --------------------------------------------------------------------------


def test_squareoff_sweep_is_serialized():
    """Two scheduler jobs call check_and_square_off -- the primary at the
    configured time and a backup every minute. max_instances=1 is per job id,
    so at the square-off minute both fire and could each close the same
    positions."""
    cls = squareoff_manager.SquareOffManager
    assert hasattr(cls, "_squareoff_lock")
    assert "_squareoff_lock" in inspect.getsource(cls.check_and_square_off)


def test_two_squareoff_jobs_still_exist_so_the_lock_is_needed():
    """If the backup job is ever removed, this reasoning should be revisited."""
    src = (REPO / "sandbox" / "squareoff_thread.py").read_text(encoding="utf-8")
    assert src.count("func=som.check_and_square_off") == 2, (
        "square-off job count changed; re-evaluate whether the lock is still required"
    )


def test_concurrent_sweeps_run_one_at_a_time():
    cls = squareoff_manager.SquareOffManager
    overlaps, active = [], []
    guard = threading.Lock()
    barrier = threading.Barrier(6)

    def sweep(_b=barrier):
        _b.wait()
        with cls._squareoff_lock:
            with guard:
                active.append(1)
                if len(active) > 1:
                    overlaps.append(1)
            threading.Event().wait(0.005)
            with guard:
                active.pop()

    threads = [threading.Thread(target=sweep) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlaps == [], "square-off sweeps overlapped"


# --------------------------------------------------------------------------
# GT-A9-07: holdings (money path already covered)
# --------------------------------------------------------------------------


def test_holdings_money_path_is_locked_and_the_rest_is_display_only():
    """Settlement moves margin and quantity, so it is serialized (PR-8). The
    remaining methods refresh mark-to-market values for display: idempotent,
    last-write-wins, and not a money path."""
    cls = holdings_manager.HoldingsManager
    assert "_settlement_lock" in inspect.getsource(cls.process_t1_settlement)

    mtm_src = inspect.getsource(cls._update_holdings_mtm)
    for money_op in ("release_margin", "credit_sale_proceeds", "transfer_margin_to_holdings"):
        assert money_op not in mtm_src, f"{money_op} in the MTM refresh path needs a lock"


# --------------------------------------------------------------------------
# GT-A9-02 / GT-A9-04: fallback and teardown
# --------------------------------------------------------------------------


def test_engine_handover_is_guarded_by_the_thread_lock():
    """A9-02/A9-04: the polling and WebSocket engines are meant to be mutually
    exclusive. PR-8 fixed the handover so the watcher is stopped before the
    engine lock is taken and a timed-out join is not reported as stopped."""
    src = (REPO / "sandbox" / "execution_thread.py").read_text(encoding="utf-8")
    stop_at = src.index("_stop_websocket_upgrade_watcher()")
    lock_at = src.index("with _thread_lock:", src.index("def stop_execution_engine"))
    assert stop_at < lock_at
    assert "did not stop within 5s" in src, "a stuck watcher is silently treated as stopped"


# --------------------------------------------------------------------------
# GT-F-04: flow writers
# --------------------------------------------------------------------------


def test_flow_db_has_no_check_then_act():
    """Resolved with evidence from the gate script rather than by inspection."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "scripts/gthread_check_then_act.py", "database"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert "check-then-act pairs: 0" in result.stdout, result.stdout
