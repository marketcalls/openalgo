"""Start, stop and report on the child processes that run compiled OpenScript.

This is the half that runs INSIDE the web worker. Production is one
cooperatively scheduled worker, so everything here has to hand the worker back
immediately: starting a run means spawning a process and returning, and it never
waits for a result. The work itself is ``strategies/scripts/openscript_runner.py``,
which is an ordinary process with nothing patched in it.

**Why a child process and not a thread.** A compiled program is walked by an
engine, bar by bar, and a strategy polls the platform between bars. Neither is
something to do on the worker: one strategy computing would stop every other
request until it finished. A process also fails alone. A script that loops
forever, exhausts its memory or dies takes itself down and nothing else, and the
operator's page, feed and orders are untouched. That is the same reason the
strategy host runs a trader's Python in a process of its own, and the same reason
the market data proxy is a child process rather than a thread.

**The patterns below are the strategy host's, copied rather than imported.**
``blueprints/python_strategy.py`` already owns process isolation per strategy, a
registry of what is running, and per-strategy logs under ``log/strategies``.
Importing a blueprint into a service would drag the whole web layer behind it, so
the shape is copied and the places it is copied from are named. What is
deliberately NOT copied is the scheduler: there is exactly one in this
application, ``init_scheduler`` in that blueprint, and a second would be a second
set of jobs nobody is looking at.

Three things in here are the reason it reads the way it does:

- **The registry lock is a real one.** Under the production server a plain
  ``threading.RLock`` is green: it belongs to the hub and can only pass a waiter
  from one greenlet to another. This dictionary is read while a process is being
  reaped, so the lock is taken from ``utils/real_threading`` and the section it
  guards is in-memory bookkeeping and nothing else.
- **No wait here is served by C.** ``Popen.wait(timeout=...)`` blocks inside
  ``waitpid`` or its equivalent, which is not a yield point, so on the production
  server it would stop every request for the length of the timeout rather than
  just this one. Every wait below polls ``poll()`` against a deadline and sleeps
  between checks, which the server turns into a yield.
- **The wait happens outside the lock.** A strategy takes as long to stop as it
  takes to notice it was asked, and holding a process-wide lock across that would
  stall every other start, stop and status read.

**Nothing here places an order and nothing here decides where one goes.** The
child reaches the platform's own order path, which reads the analyzer toggle
before anything else, so a run's orders go where every other surface's orders go.
This service passes no destination, no mode and no override, and there is
deliberately nothing it could pass.
"""

import atexit
import os
import platform
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

import psutil
import pytz

from utils.logging import get_logger
from utils.real_threading import RLock

logger = get_logger(__name__)

# The timezone every timestamp a trader reads is written in, as the strategy host
# already writes them.
IST = pytz.timezone("Asia/Kolkata")

# Where per-run logs go. The same folder the strategy host uses, deliberately: a
# second log location is a second place an operator has to know about, and the
# routes that list and read a strategy's logs already look here.
LOGS_DIR = Path("log") / "strategies"

# The program that runs inside the child.
RUNNER_SCRIPT = Path("strategies") / "scripts" / "openscript_runner.py"

# What a run is called. Namespaced so a run can never collide with a strategy the
# Python host is running: both write into one log folder and both keep a registry
# keyed by an id, and two different things answering to one id is how a stop
# reaches the wrong process.
ID_PREFIX = "openscript"

# A script name this service will start. The same shape the route that stores
# them accepts, restated because this module builds a command line out of it: a
# name with a separator, a dot segment or a dash at the front would be an
# argument rather than a file.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.oscript$")

# The same, for the instrument and interval a run is started on. They reach a
# command line too.
_SAFE_FIELD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

#: What is running now: ``{run_id: {"process", "pid", "started_at", "log_file", ...}}``.
RUNNING_RUNS: dict[str, dict] = {}

#: Runs whose process is being terminated right now. ``stop`` waits outside the
#: lock, so between claiming a run and writing its bookkeeping back it is in
#: neither dictionary. Without a marker for that window a start arriving mid-wait
#: would see the id as absent and launch a replacement beside a process that is
#: still alive, and one of the two would then be running with nothing tracking it.
STOPPING_RUNS: set[str] = set()

#: Guards the two above and nothing else. Real, not green: see the module note.
PROCESS_LOCK = RLock()

OS_TYPE = platform.system().lower()
IS_WINDOWS = OS_TYPE == "windows"


def run_id_for(script: str) -> str:
    """The id one script's run is known by, in the registry and in its log name."""
    return f"{ID_PREFIX}_{script[: -len('.oscript')] if script.endswith('.oscript') else script}"


def _ist_now() -> datetime:
    return datetime.now(IST)


def _subprocess_arguments() -> dict:
    """The platform-specific half of spawning a child, as the strategy host spawns one.

    A process group of its own on every platform, so that stopping a run reaches
    whatever the run started rather than orphaning it, and no console window on
    the platform that would otherwise open one.
    """
    arguments: dict = {"stderr": subprocess.STDOUT}
    if IS_WINDOWS:
        arguments["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        arguments["startupinfo"] = info
    else:
        arguments["start_new_session"] = True
    return arguments


def log_file_for(run_id: str, started: datetime | None = None) -> Path:
    """The log file one run writes into.

    Named the way the strategy host names one, ``<id>_<when>_IST.log`` under
    ``log/strategies``, because the routes that list a strategy's logs and read
    one back match on exactly that shape. A run that wrote somewhere else, or
    under another name, would be a run whose log nothing on this platform can
    find.
    """
    when = started or _ist_now()
    return LOGS_DIR / f"{run_id}_{when.strftime('%Y%m%d_%H%M%S')}_IST.log"


def logs_for(run_id: str) -> list[Path]:
    """Every log this run has written, newest first."""
    if not LOGS_DIR.is_dir():
        return []
    found = [one for one in LOGS_DIR.glob(f"{run_id}_*.log") if one.is_file()]
    return sorted(found, key=lambda one: one.name, reverse=True)


def _wait_for_exit(process: subprocess.Popen, timeout: float) -> bool:
    """Poll for a child to exit, without a wait the server cannot interrupt.

    ``Popen.wait(timeout=...)`` blocks inside C on every platform, and on the
    production server one OS thread runs every request, so that call would stop
    the whole application for the length of the timeout rather than only this
    caller. ``poll()`` reads the exit status without waiting and reaps the child
    once it has gone, so polling it against a deadline yields in between.

    This is the strategy host's ``wait_for_popen_exit``, copied for the reason
    given at the top of this module. Returns True once the process is gone.
    """
    if process.poll() is not None:
        return True

    deadline = monotonic() + timeout
    while monotonic() < deadline:
        sleep(0.1)
        if process.poll() is not None:
            return True
    return process.poll() is not None


def _terminate(process: subprocess.Popen, pid: int, gentle: float = 5.0, forced: float = 2.0) -> bool:
    """Ask a run to stop, and insist if it does not. True once it is gone.

    Gentle first, because a run asked to stop finishes the bar it is on and
    leaves, which is what keeps its ledger and its log consistent with what it
    actually sent. The forced signal exists for a run that cannot answer.
    """
    try:
        if IS_WINDOWS:
            process.terminate()
            if _wait_for_exit(process, gentle):
                return True
            process.kill()
            return _wait_for_exit(process, forced)

        # The run has a session of its own, so the signal goes to the group and
        # anything it started goes with it.
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            process.terminate()

        if _wait_for_exit(process, gentle):
            return True

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            process.kill()
        return _wait_for_exit(process, forced)

    except ProcessLookupError:
        return True
    except Exception:
        logger.exception("Could not stop the OpenScript run with process id %s", pid)
        return process.poll() is not None


def _process_is_alive(pid: int | None) -> bool:
    """Whether a process id still names something running."""
    if not pid:
        return False
    try:
        if psutil.pid_exists(pid):
            found = psutil.Process(pid)
            return found.is_running() and found.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def _api_key_for(user_id: str | None) -> str | None:
    """The key the child authenticates with, or nothing.

    Read here and handed to the child in its environment, which is how the
    strategy host hands one to a trader's script. Read outside the registry lock,
    deliberately: a database read is not in-memory bookkeeping and a greenlet
    holding a real lock across one stops every other request.
    """
    if not user_id:
        return None
    try:
        from database.auth_db import get_api_key_for_tradingview

        return get_api_key_for_tradingview(user_id)
    except Exception:
        logger.exception("Could not read the API key for an OpenScript run")
        return None


def start_run(
    script: str,
    symbol: str,
    exchange: str,
    interval: str,
    user_id: str | None = None,
    product: str = "",
    history_days: int = 5,
    poll_seconds: float = 15.0,
) -> tuple[bool, str]:
    """Start one script in a process of its own and return at once.

    It does not wait for the run to load its program, reach the platform or place
    anything. There is nothing to wait for that would be worth stopping every
    other request over, and the answer to "did it start" is in the run's own log a
    moment later. Whether the script has a compiled program, whether the engine is
    installed and whether the instrument answers are all the child's to find out,
    and each of them is a sentence in that log naming the script.
    """
    if not _SAFE_NAME.match(script or ""):
        return False, (
            f"{script!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )
    for name, value in (("instrument", symbol), ("exchange", exchange), ("interval", interval)):
        if not _SAFE_FIELD.match(value or ""):
            return False, f"{value!r} is not {'an' if name == 'exchange' else 'a'} {name} this can start a run on"

    run_id = run_id_for(script)

    with PROCESS_LOCK:
        if run_id in RUNNING_RUNS:
            return False, f"{script} is already running"
        if run_id in STOPPING_RUNS:
            return False, f"{script} is still stopping, try again in a moment"

    runner = RUNNER_SCRIPT.resolve()
    if not runner.is_file():
        logger.error("The OpenScript runner is missing at %s", runner)
        return False, "The program that runs a script is missing from this installation"

    # Everything that can fail slowly happens before the lock is taken again.
    api_key = _api_key_for(user_id)
    started = _ist_now()
    log_file = log_file_for(run_id, started)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as unwritable:
        logger.exception("Could not create the OpenScript log folder")
        return False, f"The folder logs are written to could not be created: {unwritable}"

    try:
        handle = open(log_file, "w", encoding="utf-8", buffering=1)
    except OSError as unwritable:
        logger.exception("Could not open a log for the OpenScript run %s", run_id)
        return False, f"The log for this run could not be opened: {unwritable}"

    environment = os.environ.copy()
    environment["STRATEGY_ID"] = run_id
    environment["STRATEGY_NAME"] = script
    environment.setdefault("OPENALGO_HOST", "http://127.0.0.1:5000")
    if api_key:
        environment["OPENALGO_API_KEY"] = api_key

    command = [
        sys.executable,
        "-u",
        str(runner),
        "--script",
        script,
        "--symbol",
        symbol,
        "--exchange",
        exchange,
        "--interval",
        interval,
        "--history-days",
        str(int(history_days)),
        "--poll-seconds",
        str(float(poll_seconds)),
        "--strategy-name",
        run_id,
    ]
    if product:
        command += ["--product", product]

    arguments = _subprocess_arguments()
    arguments["stdout"] = handle
    arguments["cwd"] = str(Path.cwd())
    arguments["env"] = environment

    try:
        handle.write(f"=== Run started at {started.strftime('%Y-%m-%d %H:%M:%S IST')} ===\n")
        handle.flush()
        process = subprocess.Popen(command, **arguments)
    except Exception as failed:
        handle.close()
        logger.exception("Could not start the OpenScript run %s", run_id)
        return False, f"This script could not be started: {failed}"
    finally:
        # The child has inherited the descriptor, so the parent's copy is a second
        # one held open for the life of the run. Production is a single worker
        # that never restarts, so one held per run accumulates until the process
        # runs out of them. The child's is the authoritative one and stays open.
        try:
            handle.close()
        except OSError:
            logger.debug("The parent side of the log for %s did not close cleanly", run_id)

    with PROCESS_LOCK:
        RUNNING_RUNS[run_id] = {
            "process": process,
            "pid": process.pid,
            "started_at": started,
            "log_file": str(log_file),
            "script": script,
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
        }

    logger.info("Started the OpenScript run %s as process %s", run_id, process.pid)
    return True, f"{script} started at {started.strftime('%H:%M:%S IST')}"


def stop_run(script_or_run_id: str) -> tuple[bool, str]:
    """Stop one run and reap its process.

    The claim is taken under the lock and the waiting is done outside it, which is
    the strategy host's shape and is there for the same reason: a run takes as
    long to stop as it takes to notice, and holding the registry lock across that
    stalls every other caller of it.

    A run that outlives both signals goes back into the registry. It is still out
    there, and dropping the only record of it would leave a process placing orders
    with nothing able to stop it.
    """
    run_id = _as_run_id(script_or_run_id)

    with PROCESS_LOCK:
        if run_id in STOPPING_RUNS:
            return False, "That run is already stopping"
        held = RUNNING_RUNS.pop(run_id, None)
        if held is None:
            return False, "That run is not running"
        STOPPING_RUNS.add(run_id)

    try:
        process = held["process"]
        pid = held.get("pid")
        stopped = _terminate(process, pid)
        if not stopped:
            with PROCESS_LOCK:
                RUNNING_RUNS.setdefault(run_id, held)
            return False, "That run did not stop. It is still running."
    finally:
        # On every path, including the one above, or the run can never be started
        # or stopped again for the life of this worker.
        with PROCESS_LOCK:
            STOPPING_RUNS.discard(run_id)

    logger.info("Stopped the OpenScript run %s", run_id)
    return True, f"{held.get('script', run_id)} stopped"


def _as_run_id(given: str) -> str:
    """A caller may name the script or the run. Both reach the same id."""
    return given if given.startswith(f"{ID_PREFIX}_") else run_id_for(given)


def is_running(script_or_run_id: str) -> bool:
    """Whether this run is tracked and its process is still there."""
    run_id = _as_run_id(script_or_run_id)
    with PROCESS_LOCK:
        held = RUNNING_RUNS.get(run_id)
        process = held["process"] if held else None
    return process is not None and process.poll() is None


def status_of(script_or_run_id: str) -> dict | None:
    """What is known about one run, or nothing when it is not running.

    A copy, and never the registry's own entry: it carries the process object,
    which a caller outside this module has no business holding.
    """
    run_id = _as_run_id(script_or_run_id)
    with PROCESS_LOCK:
        held = RUNNING_RUNS.get(run_id)
        if held is None:
            return None
        process = held["process"]
        return {
            "run": run_id,
            "script": held.get("script"),
            "symbol": held.get("symbol"),
            "exchange": held.get("exchange"),
            "interval": held.get("interval"),
            "pid": held.get("pid"),
            "started_at": held.get("started_at"),
            "log_file": held.get("log_file"),
            "running": process.poll() is None,
            "exit_code": process.poll(),
        }


def running_runs() -> list[dict]:
    """Every run this worker is tracking, as copies."""
    with PROCESS_LOCK:
        ids = list(RUNNING_RUNS)
    found = [status_of(one) for one in ids]
    return [one for one in found if one is not None]


def reap_finished_runs() -> list[str]:
    """Drop every run whose process has finished, and say which.

    A run ends by itself more often than it is stopped: it refuses to start
    because nothing compiled, or the script raised a diagnostic and stopped
    itself. Nothing notices that on its own, so without this the registry would go
    on reporting a run that ended hours ago and would refuse to start it again.

    ``poll()`` is what reaps the child, so calling it here is not only the
    question but also the answer: a child nobody polls stays a zombie.
    """
    finished = []
    with PROCESS_LOCK:
        for run_id, held in list(RUNNING_RUNS.items()):
            process = held["process"]
            over = process.poll() is not None
            if not over and not _process_is_alive(held.get("pid")):
                over = True
            if over:
                finished.append(run_id)
                del RUNNING_RUNS[run_id]

    for run_id in finished:
        logger.info("The OpenScript run %s has finished", run_id)
    return finished


def stop_every_run() -> list[str]:
    """Stop every run this worker started, and say which were stopped.

    A child outlives its parent, so an application that exited without doing this
    would leave a strategy polling and placing orders with nothing left that could
    stop it. That is the worst shape this can fail in, and it is the one that
    happens on an ordinary restart rather than on anything exotic.

    The ids are taken under the lock and the stopping is done outside it, because
    ``stop_run`` takes the lock itself and waits for each process: holding it
    across the loop would put every termination in a queue behind the one before.

    **What this does not cover, said rather than implied.** A worker that is killed
    outright runs nothing, so its children are orphaned, and this service keeps no
    record on disk that a later worker could adopt them from. See the report beside
    this change.
    """
    with PROCESS_LOCK:
        ids = list(RUNNING_RUNS)
    if ids:
        logger.info("Stopping %d OpenScript run(s) before this worker exits", len(ids))

    stopped = []
    for run_id in ids:
        try:
            ok, _ = stop_run(run_id)
        except Exception:
            logger.exception("An OpenScript run did not stop cleanly at exit")
            continue
        if ok:
            stopped.append(run_id)
    return stopped


# Registered at import, which is what the strategy host does with its own, and
# for the same reason: the thing that must not be forgotten is the one that has to
# happen without anybody remembering to ask for it.
atexit.register(stop_every_run)
