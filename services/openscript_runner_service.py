"""Start, stop and report on the child processes that run compiled OpenScript.

This is the half that runs INSIDE the web worker. Production is one
cooperatively scheduled worker, so everything here has to hand the worker back
immediately: starting a run means spawning a process and returning, and it never
waits for a result. The work itself is ``openscript_host/openscript_runner.py``,
which is an ordinary process with nothing patched in it.

**A start names the script and nothing else.** What the run is on comes from the
settings saved against that script, in ``services/openscript_run_config.py``. A
start that carried the instrument would let a scheduled run and a run started by
hand differ by one typed character, and the difference would first be visible as
an order on something nobody meant to trade. A script with no settings saved is
refused by name, saying what is missing, rather than started on a guess. The
explicit arguments are still here for a caller that already holds them, and
anything it does not pass is read from those settings.

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

Four things in here are the reason it reads the way it does:

- **The registry lock is the ordinary one, and that is the point.** Every path
  into this module is a request greenlet or a scheduled job, and under the
  production server both of those are green: the scheduler's workers are
  ordinary threads, which that server patches, and so is the main thread that
  runs the exit handler at the bottom of this file. There is no real OS thread
  here to share anything with. A lock from ``utils/real_threading`` would
  therefore be the wrong one twice over: a greenlet blocking on a real lock
  stops the single worker for every user, and a greenlet that yields while
  holding one can never be resumed to release it. ``threading.RLock`` belongs to the hub, which is the
  only world these callers live in. **If a real thread is ever given a reason to
  read this registry, it must not take this lock**: it hands the work to a
  greenlet, or the lock moves and this note moves with it.
- **No wait here is served by C.** ``Popen.wait(timeout=...)`` blocks inside
  ``waitpid`` or its equivalent, which is not a yield point, so on the production
  server it would stop every request for the length of the timeout rather than
  just this one. Every wait below polls ``poll()`` against a deadline and sleeps
  between checks, which the server turns into a yield.
- **The wait happens outside the lock.** A strategy takes as long to stop as it
  takes to notice it was asked, and holding a process-wide lock across that would
  stall every other start, stop and status read.
- **The registry heals itself.** A run ends by itself far more often than it is
  stopped, and nothing tells this module when that happens. So every function
  that reads or writes the registry first drops the entries whose process has
  gone. Nothing outside has to remember to ask, because the version that relied
  on being asked was never asked: a run that ended by itself stayed in the
  registry, and that script could not be started again for the life of the
  worker.

**Nothing here places an order and nothing here decides where one goes.** The
child reaches the platform's own order path, which reads the analyzer toggle
before anything else, so a run's orders go where every other surface's orders go.
This service passes no destination, no mode and no override, and there is
deliberately nothing it could pass.
"""

import atexit
import os
import platform
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import RLock
from time import monotonic, sleep

import psutil
import pytz

from services.openscript_run_config import (
    PRODUCTS,
    is_product,
    is_run_field,
    is_script_name,
    read_run_config,
    require_run_config,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# The timezone every timestamp a trader reads is written in, as the strategy host
# already writes them.
IST = pytz.timezone("Asia/Kolkata")

# Where per-run logs go. The same folder the strategy host uses, deliberately: a
# second log location is a second place an operator has to know about, and the
# routes that list and read a strategy's logs already look here.
LOGS_DIR = Path("log") / "strategies"

#: The program that runs inside the child.
#:
#: It belongs to the platform, not to the trader, so it lives where the platform's
#: own files live and ships in the image. It cannot live under ``strategies``:
#: that path is a named volume on a container install, and a volume is seeded
#: from the image only while it is empty, so a file the platform put there would
#: be absent on every install that already has one after an upgrade. The folder
#: it used to be in also ignores every ``.py`` in it, which would have kept it
#: out of the repository as well.
RUNNER_SCRIPT = Path("openscript_host") / "openscript_runner.py"

#: Where it used to be, read only while an installation still has it there.
#:
#: This is a migration shim and nothing more. It exists so that an install which
#: has not yet taken the move keeps working rather than answering every start
#: with a missing program, and it says so in the log each time it is used.
#: Delete it, and the branch in ``runner_program_path``, once no supported
#: install has a runner under ``strategies``.
LEGACY_RUNNER_SCRIPT = Path("strategies") / "scripts" / "openscript_runner.py"

# What a run is called. Namespaced so a run can never collide with a strategy the
# Python host is running: both write into one log folder and both keep a registry
# keyed by an id, and two different things answering to one id is how a stop
# reaches the wrong process.
ID_PREFIX = "openscript"

# What a script name, an instrument, an exchange, an interval and a product may
# look like is decided in one place, ``services/openscript_run_config.py``, and
# imported from there. Every one of them reaches the command line built below,
# and a value the settings accepted but this refused would be a run that could be
# saved and never started.

#: What is running now: ``{run_id: {"process", "pid", "started_at", "log_file", ...}}``.
RUNNING_RUNS: dict[str, dict] = {}

#: Runs whose process is being terminated right now. ``stop`` waits outside the
#: lock, so between claiming a run and writing its bookkeeping back it is in
#: neither dictionary. Without a marker for that window a start arriving mid-wait
#: would see the id as absent and launch a replacement beside a process that is
#: still alive, and one of the two would then be running with nothing tracking it.
STOPPING_RUNS: set[str] = set()

#: Run ids claimed by a start that has not finished spawning yet.
#:
#: CLAUDE.md's order path invariant is 'claim under the same lock that checks',
#: and it is here for the same reason it is there. Starting a child is slow:
#: an API key is read, a folder is made, a log is opened and a process is
#: spawned. Doing that between the check and the write leaves a window where
#: every concurrent start sees an empty registry and every one of them spawns.
#: Measured before this existed: eight simultaneous starts of one script gave
#: eight children, all trading the same strategy on the same account.
#:
#: A claim is not a run, so it is kept here rather than as a placeholder in
#: RUNNING_RUNS: the sweep drops any entry with no process, and a claim has
#: none yet, so a placeholder would be swept the moment it was made.
STARTING_RUNS: set[str] = set()

#: Guards the two above and nothing else. The hub's own lock, not a real one:
#: see the module note for why that is the right one here.
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


def runner_program_path() -> Path | None:
    """Where the program that runs a script is, or nothing if this install has none.

    Two places are looked at and only two, both of them written down above. The
    first is where the program belongs. The second is where it used to be, and
    finding it there is reported every time, because an install left on the old
    path loses the program the next time its container is rebuilt.
    """
    canonical = RUNNER_SCRIPT.resolve()
    if canonical.is_file():
        return canonical

    legacy = LEGACY_RUNNER_SCRIPT.resolve()
    if legacy.is_file():
        logger.warning(
            "The OpenScript runner is still at %s. It belongs at %s, which ships with the "
            "platform: the folder it is in now is a mounted volume on a container install, so "
            "an upgrade does not deliver a file there.",
            legacy,
            canonical,
        )
        return legacy

    return None


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

    **On Windows the gentle step is a console break and not ``terminate``.**
    ``Popen.terminate`` there is ``TerminateProcess``, which is the forced step
    under a gentler name: the child gets no signal, runs no handler and stops
    wherever it happened to be, which can be between sending one leg of a bar and
    sending the other. The child is spawned into a process group of its own
    (``CREATE_NEW_PROCESS_GROUP``) precisely so a break can be delivered to it,
    and it handles ``SIGBREAK`` alongside ``SIGTERM``. Only if that is refused or
    ignored does this fall through to killing it.
    """
    try:
        if IS_WINDOWS:
            broken = False
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                broken = True
            except (OSError, ValueError, AttributeError):
                # No group to break, or the platform refused it. Say so rather
                # than reporting a gentle stop that never happened.
                logger.warning(
                    "Could not ask process %s to stop gently; it will be terminated", pid
                )
            if broken and _wait_for_exit(process, gentle):
                return True
            process.terminate()
            if _wait_for_exit(process, forced):
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
    """Whether a process id still names something running.

    **Deliberately not what decides that a run has finished.** An id can be
    reused, and where reading another process needs permission a live one is
    indistinguishable from a dead one, so an answer of False here is not evidence
    that a run has gone. Only the run's own process object may say that. This
    stays because confirming a process by id after a stop is a different question
    from deciding to forget one, and it is the question a caller checking up on a
    termination is asking.
    """
    if not pid:
        return False
    try:
        if psutil.pid_exists(pid):
            found = psutil.Process(pid)
            return found.is_running() and found.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def _forget_finished_locked() -> list[str]:
    """Drop every run whose process has gone, and say which. The caller holds the lock.

    This is what makes the registry self-healing, and every function that reads
    or writes the registry calls it first. A run ends by itself more often than
    it is stopped: it refuses to start because nothing was compiled, or the
    script raised a diagnostic and stopped itself. Nothing tells this module that
    happened, so a registry that waited to be swept would go on reporting a run
    that ended hours ago, and would refuse to start that script again for the
    life of the worker. Waiting to be swept is exactly what the previous version
    did, and nothing ever swept it.

    ``poll()`` is both the question and the answer: it reads the exit status
    without waiting, and it is also what reaps the child, so a child nobody polls
    stays a zombie holding a process slot.

    **A run is only dropped when its own process says it has gone.** Liveness by
    process id is deliberately not consulted: the id may have been reused by then,
    and on the platform where reading another process needs permission the answer
    for a live run is indistinguishable from the answer for a dead one. Dropping a
    live run would leave a strategy placing orders with nothing left that could
    stop it, which is the worst shape this can fail in and far worse than keeping
    a finished one a moment longer. For the same reason a ``poll()`` that raises
    keeps the entry.
    """
    finished = []
    for run_id, held in list(RUNNING_RUNS.items()):
        process = held.get("process")
        try:
            over = process is None or process.poll() is not None
        except Exception:
            logger.exception("Could not tell whether the OpenScript run %s is still there", run_id)
            over = False
        if over:
            del RUNNING_RUNS[run_id]
            finished.append(run_id)

    for run_id in finished:
        logger.info("The OpenScript run %s has finished", run_id)
    return finished


def _status_locked(run_id: str, held: dict) -> dict:
    """One registry entry as a caller may hold it. The caller holds the lock.

    A copy, and never the entry itself: it carries the process object, which a
    caller outside this module has no business holding.

    ``running`` and ``exit_code`` are here for a caller that reads the dictionary
    without knowing the rule above it. Since a finished run is dropped before
    anything is copied, the first is always true and the second always nothing: a
    run that has ended is not in the answer at all.
    """
    process = held.get("process")
    over = None if process is None else process.poll()
    return {
        "run": run_id,
        "script": held.get("script"),
        "symbol": held.get("symbol"),
        "exchange": held.get("exchange"),
        "interval": held.get("interval"),
        "product": held.get("product", ""),
        "pid": held.get("pid"),
        "started_at": held.get("started_at"),
        "log_file": held.get("log_file"),
        "running": over is None,
        "exit_code": over,
    }


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
    symbol: str = "",
    exchange: str = "",
    interval: str = "",
    user_id: str | None = None,
    product: str = "",
    history_days: int = 5,
    poll_seconds: float = 15.0,
) -> tuple[bool, str]:
    """Start one script in a process of its own and return at once.

    **The script name alone is enough**, and that is how a run is started: the
    instrument, the exchange, the interval, the product and the owning user come
    from the settings saved against that script. Anything passed here wins over
    what is saved, for a caller that already holds it, and a script with neither
    is refused by name saying which of the three is missing.

    It does not wait for the run to load its program, reach the platform or place
    anything. There is nothing to wait for that would be worth stopping every
    other request over, and the answer to "did it start" is in the run's own log a
    moment later. Whether the script has a compiled program, whether the engine is
    installed and whether the instrument answers are all the child's to find out,
    and each of them is a sentence in that log naming the script.
    """
    if not is_script_name(script):
        return False, (
            f"{script!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )

    saved = read_run_config(script) or {}
    symbol = symbol or saved.get("symbol") or ""
    exchange = exchange or saved.get("exchange") or ""
    interval = interval or saved.get("interval") or ""
    product = product or saved.get("product") or ""
    user_id = user_id or saved.get("user_id") or None

    if not (symbol and exchange and interval):
        # Said by the settings rather than here, so a trader reads one sentence
        # about a missing setting wherever they meet it.
        _, why = require_run_config(script)
        return False, why or (
            f"{script} has no instrument, exchange and interval to run on. Save its run "
            "settings, then start it again."
        )

    for name, value in (("instrument", symbol), ("exchange", exchange), ("interval", interval)):
        if not is_run_field(value):
            return False, f"{value!r} is not {'an' if name == 'exchange' else 'a'} {name} this can start a run on"

    # A product reaches the same command line as the three above, so it is
    # checked the same way and against the list the run itself checks it against.
    # An empty one is allowed and means the script says what it needs: one that
    # closes its position by the end of the session needs no product, and one
    # that carries a position overnight is refused inside its own run, where its
    # own declaration is known.
    if product and not is_product(product):
        return False, (
            f"{product!r} is not a product this platform sends. Use one of {', '.join(PRODUCTS)}."
        )

    run_id = run_id_for(script)

    with PROCESS_LOCK:
        _forget_finished_locked()
        if run_id in RUNNING_RUNS:
            return False, f"{script} is already running"
        if run_id in STOPPING_RUNS:
            return False, f"{script} is still stopping, try again in a moment"
        if run_id in STARTING_RUNS:
            return False, f"{script} is already starting"
        # Claimed in the hold that checked, and released in the finally below
        # whatever happens after it.
        STARTING_RUNS.add(run_id)

    try:
        return _spawn_claimed(
            script, run_id, symbol, exchange, interval, product,
            user_id, history_days, poll_seconds,
        )
    finally:
        with PROCESS_LOCK:
            STARTING_RUNS.discard(run_id)


def _spawn_claimed(
    script: str,
    run_id: str,
    symbol: str,
    exchange: str,
    interval: str,
    product: str,
    user_id: str | None,
    history_days: int,
    poll_seconds: float,
) -> tuple[bool, str]:
    """The slow half of a start, run with this script's id already claimed.

    Split out of ``start_run`` so the claim can be released in one ``finally``
    rather than on each of the seven paths that can fail between opening a log
    and registering a child. A path that forgot would leave a script that can
    never be started again for the life of the worker.
    """
    runner = runner_program_path()
    if runner is None:
        logger.error("The OpenScript runner is missing. It belongs at %s", RUNNER_SCRIPT.resolve())
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
        _forget_finished_locked()
        RUNNING_RUNS[run_id] = {
            "process": process,
            "pid": process.pid,
            "started_at": started,
            "log_file": str(log_file),
            "script": script,
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "product": product,
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
        _forget_finished_locked()
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
    """A caller may name the script or the run. Both reach the same id.

    The two are told apart by the extension and not by the prefix. Every script
    name ends ``.oscript`` (``is_script_name`` requires it) and no run id does,
    because ``run_id_for`` strips it. Testing the prefix instead read a script
    genuinely named ``openscript_something.oscript`` as though it were already a
    run id: ``start_run`` registered it under ``openscript_openscript_something``
    while ``stop_run`` and ``status_of`` looked for ``openscript_something.oscript``,
    so the run started, answered "not running" ever after, and could not be
    stopped through any route.
    """
    if given.endswith(".oscript"):
        return run_id_for(given)
    return given if given.startswith(f"{ID_PREFIX}_") else run_id_for(given)


def is_running(script_or_run_id: str) -> bool:
    """Whether this run is tracked and its process is still there."""
    run_id = _as_run_id(script_or_run_id)
    with PROCESS_LOCK:
        _forget_finished_locked()
        return run_id in RUNNING_RUNS


def status_of(script_or_run_id: str) -> dict | None:
    """What is known about one run, or nothing when it is not running.

    A copy, and never the registry's own entry. A run whose process has ended is
    not running, so it answers nothing here and its log is where the rest of its
    story is.
    """
    run_id = _as_run_id(script_or_run_id)
    with PROCESS_LOCK:
        _forget_finished_locked()
        held = RUNNING_RUNS.get(run_id)
        if held is None:
            return None
        return _status_locked(run_id, held)


def running_runs() -> list[dict]:
    """Every run this worker is tracking, as copies.

    Built in one hold rather than by asking after each id in turn, so the list is
    one answer about one moment instead of several answers about several.
    """
    with PROCESS_LOCK:
        _forget_finished_locked()
        return [_status_locked(run_id, held) for run_id, held in RUNNING_RUNS.items()]


def reap_finished_runs() -> list[str]:
    """Drop every run whose process has finished, and say which.

    The registry drops a finished run on its own, on every read and every write,
    so nothing depends on this being called. It stays because a sweep is also
    worth doing when nobody is looking: a worker where no page is open and no run
    is started still has children to reap, and a scheduled job calling this keeps
    a finished run from holding its process slot until the next request happens
    to arrive. It is the same sweep, so it can never drift from the one the rest
    of this module does.
    """
    with PROCESS_LOCK:
        return _forget_finished_locked()


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
        _forget_finished_locked()
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
