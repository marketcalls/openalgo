"""Findings from the gthread review that concern installs still on eventlet.

eventlet stays the default worker, and an install that has not opted in to
gthread must see no change. Each case below runs a real ``eventlet.monkey_patch()``
in a subprocess (it is global and cannot be undone, see
test_eventlet_cross_thread_locks.py for the pattern) and asserts that the code
the review flagged takes main's path there.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

ROOT = Path(__file__).resolve().parent.parent

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.main.load_dotenv = dotenv.load_dotenv

import json, os, tempfile, threading, time
from pathlib import Path
from types import SimpleNamespace

from utils import runtime
assert runtime.worker_class() == "eventlet", runtime.worker_class()
assert not runtime.gthread_active()
"""


def run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
    )


def _ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert "PASSED" in result.stdout, result.stdout[-2000:]


def test_chartink_restores_nothing_and_schedulers_keep_their_defaults():
    """eventlet-neutrality-01, -04 and hosts-messaging-02."""
    _ok(
        run(
            """
            from blueprints import chartink
            from blueprints import python_strategy as ps

            # Nothing booked at import, and the scheduler has APScheduler's own
            # one second misfire grace, as on main.
            assert chartink.scheduler.get_job(chartink._SQUAREOFF_RESTORE_JOB_ID) is None
            assert chartink.scheduler._job_defaults["misfire_grace_time"] == 1
            ps.init_scheduler()
            assert ps.SCHEDULER._job_defaults["misfire_grace_time"] == 1

            # Even called directly, the restore reads nothing and books nothing.
            reads = []

            class Query:
                @staticmethod
                def all():
                    reads.append(1)
                    return [SimpleNamespace(id=1, is_intraday=True, squareoff_time="15:10",
                                            is_active=False)]

            chartink.ChartinkStrategy = SimpleNamespace(query=Query)
            assert chartink.restore_squareoff_jobs() is True
            chartink._restore_squareoff_on_activation(
                SimpleNamespace(id=1, is_intraday=True, squareoff_time="15:10", is_active=True)
            )
            assert reads == []
            assert chartink.scheduler.get_job("squareoff_1") is None
            print("PASSED")
            """
        )
    )


def test_symbol_reload_drops_the_previous_generation_first():
    """core-01: two symbol universes at once raised the peak on every install."""
    _ok(
        run(
            """
            import database.symbol as symbol_module
            import database.token_db_enhanced as tde

            def rows(expiry):
                return [
                    SimpleNamespace(symbol=f"NIFTY{expiry}{i}CE", brsymbol=f"B{i}", name="NIFTY",
                                    exchange="NFO", brexchange="NFO", token=f"{expiry}{i}",
                                    expiry=expiry, strike=float(i), lotsize=50,
                                    instrumenttype="OPTIDX", tick_size=0.05)
                    for i in range(50)
                ]

            cache = tde.BrokerSymbolCache()
            seen = []

            class Query:
                def __init__(self, expiry):
                    self.expiry = expiry

                def all(self):
                    seen.append(cache.cache_loaded)
                    return rows(self.expiry)

            symbol_module.SymToken.query = Query("30-DEC-27")
            assert cache.load_all_symbols("zerodha") is True
            symbol_module.SymToken.query = Query("27-JAN-28")
            assert cache.load_all_symbols("zerodha") is True
            assert seen == [False, False], seen
            assert cache.cache_loaded and cache.next_reset_time is not None
            print("PASSED")
            """
        )
    )


def test_quote_fanouts_leave_no_threads_and_internal_threads_are_not_judged():
    """eventlet-neutrality-10.

    Flattrade and Definedge fanned quotes out on a shared pool whose threads
    stay for good, and the health monitor counted them, with the event bus's
    order-update lane and the hub worker, against eventlet's unchanged
    thresholds. Off gthread each fan-out has a pool of its own again, as on
    main, and the two internal threads are not judged.
    """
    _ok(
        run(
            """
            from broker.definedge.api import data as definedge_data
            from broker.flattrade.api import data as flattrade_data
            from utils import health_monitor as hm

            before = threading.active_count()
            with flattrade_data._quote_pool() as pool:
                assert [f.result() for f in [pool.submit(pow, 2, n) for n in range(20)]]
            with definedge_data._quote_pool(8) as pool:
                assert [f.result() for f in [pool.submit(pow, 3, n) for n in range(8)]]
            eventlet.sleep(0.2)
            assert threading.active_count() == before, (before, threading.active_count())

            names = ["MainThread"] + [f"worker-{i}" for i in range(48)] + [
                "eventbus-critical_0", "eventbus-critical_1", "openalgo-hub-worker",
            ]
            fake = [SimpleNamespace(ident=i, name=n, daemon=True, is_alive=lambda: True)
                    for i, n in enumerate(names)]
            threading.enumerate = lambda: fake
            hm.HealthAlert.create_alert = staticmethod(lambda **k: None)
            hm.HealthAlert.auto_resolve_alerts = staticmethod(lambda *a, **k: None)
            metrics = hm.get_thread_metrics()
            # 52 threads, 3 of them the ones this release added: judged as 49.
            assert metrics["count"] == 52, metrics["count"]
            assert metrics["uncounted"] == 3
            assert metrics["status"] == "pass", metrics["status"]
            print("PASSED")
            """
        )
    )
