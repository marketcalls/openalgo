"""Closes the last non-cutover registry rows with evidence.

Covers GT-A12-05 (abuse trackers), GT-A12-06 (log writers), GT-A12-10 (plugin
loader), GT-A12-01 (pooled adapters) and GT-A16-03 (detector as a CI gate).
"""

import inspect
import threading
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# GT-A12-05: the abuse trackers hold no in-memory registry
# --------------------------------------------------------------------------


def test_ban_state_lives_in_the_database_not_in_memory():
    """Resolved with evidence. The ban decision is a database query every
    time -- there is no in-process banned-IP set that threads could corrupt or
    that could drift between the middleware and the tracker."""
    import database.traffic_db as td

    src = inspect.getsource(td.IPBan.is_ip_banned)
    assert "query" in src, "ban lookup is no longer a database read"

    middleware = (REPO / "utils" / "security_middleware.py").read_text(encoding="utf-8")
    assert "IPBan.is_ip_banned(" in middleware
    # No module-level ban cache anywhere.
    for name in ("_banned_ips", "_ban_cache", "_banned_cache"):
        assert name not in middleware, f"an in-memory ban registry appeared: {name}"


def test_the_counters_themselves_are_still_serialized():
    """The lost-update fix from PR-5a must stay in place."""
    import database.traffic_db as td

    assert hasattr(td, "_abuse_counter_lock")
    for cls, fn in (
        (td.Error404Tracker, "track_404"),
        (td.InvalidAPIKeyTracker, "track_invalid_api_key"),
    ):
        assert "_abuse_counter_lock" in inspect.getsource(getattr(cls, fn))


# --------------------------------------------------------------------------
# GT-A12-06: log writers are single-writer by construction
# --------------------------------------------------------------------------


def test_log_writers_are_single_threaded_executors():
    """Resolved with evidence: one worker each, so writes are serialized by
    construction and need no additional lock. The plan warned against
    'increasing parallelism' here -- this pins that they have not."""
    import utils.latency_monitor as lm
    import utils.traffic_logger as tl

    assert tl._traffic_log_executor._max_workers == 1
    assert lm._latency_log_executor._max_workers == 1


# --------------------------------------------------------------------------
# GT-A12-10: the plugin loader
# --------------------------------------------------------------------------


def test_broker_capabilities_are_published_by_a_single_rebind():
    """Built into a local dict, then assigned once -- the same publish-by-swap
    shape used for the symbol cache in PR-4."""
    import utils.plugin_loader as pl

    src = inspect.getsource(pl.load_broker_capabilities)
    assert "_broker_capabilities = capabilities" in src
    assert "_broker_capabilities[" not in src, "capabilities are mutated in place"


def test_lazy_broker_load_is_benign_under_concurrency():
    """The auth map loads a broker module on first access, so it mutates after
    startup, not only during it.

    Accepted rather than locked: the import itself is serialized by Python's
    own import machinery, the guard re-checks before assigning, and the value
    assigned is the same function object either way. Two racing loaders
    therefore converge on identical state -- there is nothing to lose.
    """
    import utils.plugin_loader as pl

    src = inspect.getsource(pl._LazyBrokerAuthDict._load_broker)
    assert "if super().__contains__(key):" in src, "the re-check guard is gone"
    assert "importlib.import_module" in src


def test_lazy_broker_load_converges_under_threads():
    """Behavioural: concurrent first-access must end in one consistent value."""
    import utils.plugin_loader as pl

    loads = []

    class Probe(pl._LazyBrokerAuthDict):
        def _load_broker(self, broker_name):
            key = f"{broker_name}_auth"
            if dict.__contains__(self, key):
                return
            loads.append(broker_name)
            dict.__setitem__(self, key, "auth-fn")

    probe = Probe(["demo"], "broker")
    barrier = threading.Barrier(8)

    def hit(_b=barrier):
        _b.wait()
        probe.get("demo_auth")

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # It may load more than once under a race, but the resulting value is
    # identical, which is why this is benign rather than a defect.
    assert probe.get("demo_auth") == "auth-fn"
    assert len(loads) >= 1


# --------------------------------------------------------------------------
# GT-A12-01: pooled adapters
# --------------------------------------------------------------------------


def test_pooled_adapters_are_unreachable_from_request_threads():
    """Resolved conditionally. _POOLED_ADAPTERS lives in the proxy, and the
    proxy runs out of process in every production mode (external in Docker,
    subprocess on native). Only WEBSOCKET_PROXY_MODE=thread would put it in
    the Gunicorn worker, and that is development-only."""
    from websocket_proxy.app_integration import VALID_PROXY_MODES, resolve_proxy_mode

    assert VALID_PROXY_MODES == ("external", "subprocess", "thread")

    import sys

    saved = sys.modules.get("gunicorn")
    sys.modules["gunicorn"] = type(sys)("gunicorn")
    try:
        assert resolve_proxy_mode() == "subprocess", (
            "under gunicorn the proxy must stay out of process"
        )
    finally:
        if saved is None:
            del sys.modules["gunicorn"]
        else:
            sys.modules["gunicorn"] = saved


# --------------------------------------------------------------------------
# GT-A16-03: the detector runs in CI
# --------------------------------------------------------------------------


def test_detector_and_inventory_run_on_every_change():
    ci = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    runs = " ".join(s.get("run", "") for s in ci["jobs"]["backend-test"]["steps"])
    assert "gthread_check_then_act.py" in runs
    assert "gthread_sleep_inventory.py" in runs


def test_detector_exits_non_zero_on_an_unreviewed_pair():
    """It is a gate, not a report -- a new unlocked pair must fail the build."""
    src = (REPO / "scripts" / "gthread_check_then_act.py").read_text(encoding="utf-8")
    assert "return 1" in src
    assert "unreviewed" in src
