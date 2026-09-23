"""Delta Exchange's option chain lookup gives its SQLite connection back.

``BrokerData.get_option_chain`` read the master contract through
``SymToken.query``, the query property of the plugin's own scoped session,
and never closed it. With ``autocommit=False`` the session keeps its
connection checked out after ``query.all()``. Under eventlet each request ran
on a fresh greenlet, so the greenlet-local session died with it. Under the
gthread worker threads are pooled and never exit: the app's teardown releases
it after a request, but a thread outside a request (a scheduler, an event-bus
callback, a strategy loop) keeps that connection, a file descriptor, until the
worker stops.

The lookup now runs inside ``with db_session() as session``, which closes the
session on the way out. The case runs in a child process against its own
SQLite file, so the master-contract schema it creates touches nothing else.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CHILD = """
import threading

from sqlalchemy import event

from broker.deltaexchange.database import master_contract_db as mcdb
from broker.deltaexchange.api.data import BrokerData

mcdb.init_db()
with mcdb.db_session() as session:
    for kind, strike in (("CE", 100.0), ("PE", 100.0), ("CE", 200.0)):
        session.add(mcdb.SymToken(
            symbol=f"ZZT28FEB25{int(strike)}{kind}", brsymbol=f"{kind[0]}-ZZT-{int(strike)}",
            name="ZZT", exchange="CRYPTO", brexchange="CRYPTO", token=f"{kind}{strike}",
            expiry="28-FEB-25", strike=strike, lotsize=1, instrumenttype=kind, tick_size=0.5,
        ))
    session.commit()
mcdb.db_session.remove()

counts = {"out": 0, "in": 0}
event.listen(mcdb.engine, "checkout", lambda *a: counts.__setitem__("out", counts["out"] + 1))
event.listen(mcdb.engine, "checkin", lambda *a: counts.__setitem__("in", counts["in"] + 1))

done = threading.Event()
release = threading.Event()
result = {}


def pooled_thread():
    # A thread that serves the lookup and then lives on, as a gthread pool
    # thread or a background loop does, with no app teardown after it.
    result["chain"] = BrokerData("token").get_option_chain("ZZT", "CRYPTO")
    done.set()
    release.wait(30)


worker = threading.Thread(target=pooled_thread, daemon=True)
worker.start()
assert done.wait(30), "the lookup never finished"
held = counts["out"] - counts["in"]
release.set()
worker.join(30)

chain = result["chain"]
print("ROWS", len(chain), [(r["instrumenttype"], r["strike"]) for r in chain])
print("HELD", held)
"""


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
            "BROKER_API_KEY": "key:::secret",
            "PYTHONPATH": str(REPO),
        }
    )
    return env


def test_a_pooled_thread_holds_no_connection_after_the_lookup(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(CHILD)],
        cwd=str(REPO),
        env=_child_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout
    assert proc.returncode == 0, out[-2000:] + proc.stderr[-4000:]
    rows = next(line for line in out.splitlines() if line.startswith("ROWS "))
    held = next(line for line in out.splitlines() if line.startswith("HELD "))
    # The lookup still answers, sorted CE before PE and by strike.
    assert rows.startswith("ROWS 3 "), rows
    assert "[('CE', 100.0), ('CE', 200.0), ('PE', 100.0)]" in rows, rows
    # And the thread that served it holds no connection afterwards.
    assert held == "HELD 0", f"{held}: a connection stayed checked out on the thread"
