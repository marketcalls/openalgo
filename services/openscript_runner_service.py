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
import json
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

from services.openscript_commands import ask as ask_to_close
from services.openscript_commands import clear as forget_instruction
from services.openscript_deployment import deployment_id, is_deployment_id
from services.openscript_run_config import (
    PRODUCTS,
    deployments_of,
    is_product,
    is_run_field,
    is_script_name,
    read_run_config,
    require_run_config,
)
from services.openscript_running import all_running, mark_running, mark_stopped
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


def run_id_for(script: str, symbol: str = "", exchange: str = "", interval: str = "") -> str:
    """The id one deployment is known by: registry key, log name and order tag.

    Minted by `openscript_deployment`, which is the one place that decides what
    a deployment is called. See it for why the instrument and the interval are
    part of the identity rather than only the script.
    """
    return deployment_id(script, symbol, exchange, interval)


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


class Adopted:
    """A child of a previous worker, wearing the face of the one that started it.

    **Why this exists.** An application killed outright runs no exit handler, so
    its strategy processes are still there and still placing orders. The next
    worker must not start a second one for each of them: that doubles every
    position, silently, and the two runs then fight over the same strategy. So
    it takes them over instead.

    Everything downstream of the registry expects the object a start produced,
    which answers ``poll``, ``send_signal``, ``terminate`` and ``kill``. A
    process this worker did not start has none of that, only an id, so this
    presents the same four over ``psutil`` and the stopping path does not have to
    know the difference. A branch there would be a second way to stop a run, and
    the one used rarely is the one that stops working.

    **Every failure is raised as the failure a ``Popen`` would raise.** The
    stopping path already handles a signal a platform will not deliver, by
    falling through to terminating: it catches what a ``Popen`` throws, and
    ``psutil`` throws its own family instead. Translating here means that path
    is written once and works for both, which on Windows is the difference
    between a console break falling back to a terminate and a run that can never
    be stopped.
    """

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        """None while it is still running, as ``Popen.poll`` answers.

        A zero stands in for an exit status this worker cannot know: it did not
        start the process, so nothing reported one to it. Every caller here
        tests whether the answer is None and none of them reads the number.
        """
        return None if _process_is_alive(self.pid) else 0

    def send_signal(self, number: int) -> None:
        self._do(lambda one: one.send_signal(number))

    def terminate(self) -> None:
        self._do(lambda one: one.terminate())

    def kill(self) -> None:
        self._do(lambda one: one.kill())

    def _do(self, act) -> None:
        try:
            act(psutil.Process(self.pid))
        except psutil.NoSuchProcess:
            # Already gone, which is what the caller was asking for. A `Popen`
            # whose child has exited raises nothing here either.
            return
        except (psutil.AccessDenied, psutil.Error, ValueError) as refused:
            # `Popen` reports a signal the platform will not deliver as an
            # OSError or a ValueError, and the stopping path catches those and
            # falls through to a harder signal. Anything else raised from here
            # would escape that and leave the run unstoppable.
            raise OSError(str(refused)) from refused


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
    name: str,
    symbol: str = "",
    exchange: str = "",
    interval: str = "",
    user_id: str | None = None,
    product: str = "",
    history_days: int = 5,
    poll_seconds: float = 15.0,
) -> tuple[bool, str]:
    """Start one deployment in a process of its own and return at once.

    **The name alone is enough**, and that is how a run is started: the
    instrument, the exchange, the interval, the product and the owning user come
    from the settings saved against that deployment. ``name`` is a deployment
    id, or a script name when that script has exactly one deployment. Anything
    passed here wins over what is saved, for a caller that already holds it, and
    a deployment with neither is refused saying which of the three is missing.

    It does not wait for the run to load its program, reach the platform or place
    anything. There is nothing to wait for that would be worth stopping every
    other request over, and the answer to "did it start" is in the run's own log a
    moment later. Whether the script has a compiled program, whether the engine is
    installed and whether the instrument answers are all the child's to find out,
    and each of them is a sentence in that log naming the script.
    """
    if not is_deployment_id(name) and not is_script_name(name):
        return False, (
            f"{name!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )

    saved = read_run_config(name) or {}
    # Which file this deployment runs. Taken from the settings, because a
    # deployment id is not a file name and cannot be turned back into one: the
    # long ones end in a digest.
    script = str(saved.get("script") or "") or (name if is_script_name(name) else "")
    if not is_script_name(script):
        _, why = require_run_config(name)
        return False, why or f"{name} is not a deployment on this server"

    symbol = symbol or saved.get("symbol") or ""
    exchange = exchange or saved.get("exchange") or ""
    interval = interval or saved.get("interval") or ""
    product = product or saved.get("product") or ""
    user_id = user_id or saved.get("user_id") or None
    # The script's own parameters, exactly as they were saved. They are not an
    # argument to this call: a run started from a page, a run started by a
    # schedule and a run started again after a restart have to be the same run,
    # and a caller that could supply its own would be a second place a strategy
    # could be sized or tuned from.
    inputs = saved.get("inputs") or {}

    if not (symbol and exchange and interval):
        # Said by the settings rather than here, so a trader reads one sentence
        # about a missing setting wherever they meet it.
        _, why = require_run_config(name)
        return False, why or (
            f"{script} has no instrument, exchange and interval to run on. Save its run "
            "settings, then start it again."
        )

    for field, value in (("instrument", symbol), ("exchange", exchange), ("interval", interval)):
        if not is_run_field(value):
            return False, (
                f"{value!r} is not {'an' if field == 'exchange' else 'a'} {field} this can "
                "start a run on"
            )

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

    # **The deployment's own id, because that is what its books are filtered
    # on.** A run tags every order with this, and the deployment's orderbook,
    # tradebook and positions are a filter on that tag: minting one here from
    # the four parts instead would tag a run's orders with an id nothing looks
    # for, and the strategy would trade all day showing an empty book.
    #
    # Worked out from the parts only when there is nothing saved to read it
    # from, which is a caller that passed the instrument straight in, or when
    # the caller overrode the instrument or the interval so that this run is not
    # the saved deployment at all.
    matches = (
        str(saved.get("symbol") or "") == symbol
        and str(saved.get("exchange") or "") == exchange
        and str(saved.get("interval") or "") == interval
    )
    run_id = (
        str(saved.get("deployment") or "")
        if matches and saved.get("deployment")
        else run_id_for(script, symbol, exchange, interval)
    )
    where = f"{script} on {symbol} {exchange} at {interval}"

    with PROCESS_LOCK:
        _forget_finished_locked()
        if run_id in RUNNING_RUNS:
            return False, f"{where} is already running"
        if run_id in STOPPING_RUNS:
            return False, f"{where} is still stopping, try again in a moment"
        if run_id in STARTING_RUNS:
            return False, f"{where} is already starting"
        # Claimed in the hold that checked, and released in the finally below
        # whatever happens after it.
        STARTING_RUNS.add(run_id)

    try:
        return _spawn_claimed(
            script, run_id, symbol, exchange, interval, product,
            user_id, history_days, poll_seconds, inputs,
        )
    finally:
        with PROCESS_LOCK:
            STARTING_RUNS.discard(run_id)


def _inputs_as_text(inputs: dict | None, run_id: str) -> str:
    """One script's parameters as the child reads them, or an empty set.

    Nothing raises. A run whose parameters could not be encoded starts on the
    script's own declared defaults, which is the behaviour of a script with no
    parameters saved and is a run a trader can read, rather than a start that
    fails over a settings map.
    """
    if not inputs:
        return "{}"
    try:
        return json.dumps(inputs, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        logger.exception("The parameters saved for %s could not be carried to its run", run_id)
        return "{}"


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
    inputs: dict | None = None,
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

    # The script's parameters go through the environment rather than the command
    # line, which carries only the fields checked against a pattern above. A
    # parameter's value is a trader's text and a script's own key, so it belongs
    # on the channel this already uses for what should not be argv: it has no
    # length limit worth worrying about and does not appear in a process list
    # beside every other run. Written even when empty, so a run started after
    # settings were cleared is not handed the previous ones by an environment
    # this worker inherited.
    environment["OPENSCRIPT_INPUTS"] = _inputs_as_text(inputs, run_id)

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

    # Recorded after the child exists, so nothing is ever noted as running that
    # was not. See `openscript_running`: this survives a restart and is what
    # brings the strategy back, and only a trader pressing Stop clears it.
    mark_running(run_id, process.pid)

    logger.info("Started the OpenScript run %s as process %s", run_id, process.pid)
    return True, f"{script} started at {started.strftime('%H:%M:%S IST')}"


def stop_run(
    script_or_run_id: str, forget: bool = True, close: bool = False
) -> tuple[bool, str]:
    """End one run and reap its process.

    **There are two ways to end a run and they are not the same thing.**
    ``close`` is which. With it False this is a *pause*: the process ends and
    whatever the run was holding stays exactly where it is, which is a trader
    taking the position back. With it True this is a *stop*: the run closes what
    it holds first and then ends, which is a trader finished with the strategy.
    A strategy that ended without closing what it opened is a position nothing
    is watching, and a strategy whose position was closed when the trader only
    meant to change a parameter is money spent for nothing. Neither can be
    guessed, so the caller says which.

    **The closing is the run's own, and it has to be.** Two deployments can hold
    the same instrument, so squaring the account's net position in it would
    close somebody else's; only the run knows its own size. It is asked through
    a file rather than a signal, because the two signals a run answers both mean
    "leave" and Windows has no third one. See `openscript_commands`.

    **A close that did not happen does not end the run.** The position is still
    there, so something has to be able to stop it: this answers False and leaves
    the run registered and running, which is the platform's own rule for a stop
    whose exit orders were refused.

    ``forget`` is whether this also means the trader no longer wants the
    deployment running. It does when somebody presses Pause or Stop, and it does
    not when the worker is going down: ending a child on the way out is correct,
    because a child outlives its parent, but it is not the trader changing their
    mind. See `openscript_running`.

    The claim is taken under the lock and the waiting is done outside it, which is
    the strategy host's shape and is there for the same reason: a run takes as
    long to stop as it takes to notice, and holding the registry lock across that
    stalls every other caller of it.

    A run that outlives both signals goes back into the registry. It is still out
    there, and dropping the only record of it would leave a process placing orders
    with nothing able to stop it.
    """
    run_id = _as_run_id(script_or_run_id)

    if close:
        gone, why = _close_and_wait(run_id)
        if not gone:
            return False, why

    with PROCESS_LOCK:
        _forget_finished_locked()
        if run_id in STOPPING_RUNS:
            return False, "That run is already stopping"
        held = RUNNING_RUNS.pop(run_id, None)
        if held is None:
            if close:
                # It closed its position and ended by itself, which the sweep
                # above has already noticed. That is the whole of what was
                # asked for, so it is a success and not a missing run.
                if forget:
                    mark_stopped(run_id)
                forget_instruction(run_id)
                logger.info("Closed and stopped the OpenScript run %s", run_id)
                return True, "closed and stopped"
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

    if forget:
        mark_stopped(run_id)
    forget_instruction(run_id)

    what = "closed and stopped" if close else "paused"
    logger.info("The OpenScript run %s was %s", run_id, what)
    return True, f"{held.get('script', run_id)} {what}"


#: How long to give a run to close what it holds and leave, and how often to
#: look while it does.
#:
#: Long enough for a market order to reach a broker and come back, which is
#: seconds rather than milliseconds, and not so long that a page is left
#: waiting: the deployment gives a request five minutes, and a caller that has
#: waited this long is better told what is happening than held further.
CLOSE_SECONDS = 25.0
CLOSE_LOOK = 0.5


def _close_and_wait(run_id: str) -> tuple[bool, str]:
    """Ask a run to close what it holds and leave. True once it has gone.

    Answers False with the reason while it is still there, and leaves it
    running: a run that did not close is a run still holding a position, and
    something has to be able to stop it.
    """
    with PROCESS_LOCK:
        held = RUNNING_RUNS.get(run_id)
    if held is None:
        return False, "That run is not running"

    ask_to_close(run_id)

    process = held.get("process")
    until = monotonic() + CLOSE_SECONDS
    while monotonic() < until:
        try:
            if process is not None and process.poll() is not None:
                return True, ""
        except (OSError, ValueError, AttributeError):
            # A process this worker can no longer read is one it can no longer
            # wait for. Treated as still here, which leaves the run registered.
            break
        sleep(CLOSE_LOOK)

    forget_instruction(run_id)
    return False, (
        "This strategy did not close its position in time, so it is still running and still "
        "holding it. Its own log says what happened. Deal with the position and stop it again, "
        "or use Pause to end the strategy and keep the position."
    )


def _as_run_id(given: str) -> str:
    """A caller may name the deployment or the script. Both reach one id.

    The two are told apart by the extension and not by the prefix. Every script
    name ends ``.oscript`` (``is_script_name`` requires it) and no deployment id
    does. Testing the prefix instead read a script genuinely named
    ``openscript_something.oscript`` as though it were already a run id:
    ``start_run`` registered it under ``openscript_openscript_something`` while
    ``stop_run`` and ``status_of`` looked for ``openscript_something.oscript``,
    so the run started, answered "not running" ever after, and could not be
    stopped through any route.

    **A script name is resolved through its runs first and its settings
    second**, because the id now carries the instrument and the interval and
    cannot be worked out from the name alone.

    The registry is asked first on purpose. What a caller naming a file means is
    "the run of this file", and a run started with an instrument passed straight
    to `start_run` has an id no settings file knows: resolving only through the
    settings would answer an id matching nothing, and a run that is up could not
    be stopped or asked about by the only name its caller has.

    A script running twice, or deployed twice and running neither, answers an id
    that matches no run. That is deliberate: stopping whichever of two
    deployments happened to be looked at first would stop a position on an
    instrument the caller never named.
    """
    if not given.endswith(".oscript") and given.startswith(f"{ID_PREFIX}_"):
        return given

    script = given if given.endswith(".oscript") else f"{given}.oscript"

    with PROCESS_LOCK:
        running = [
            run_id for run_id, held in RUNNING_RUNS.items() if held.get("script") == script
        ]
    if len(running) == 1:
        return running[0]
    if running:
        return run_id_for(script)

    theirs = deployments_of(script)
    if len(theirs) == 1:
        return next(iter(theirs))
    return run_id_for(script)


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


def restore_runs() -> tuple[int, int]:
    """Put back what a trader had running, and say how much was taken over.

    Answers how many were adopted and how many were started fresh.

    **Adopt first, start second, and the order is the safety.** A worker that
    went down cleanly stopped its children, so there is nothing alive and each
    one is started again. A worker that was killed outright did not, so its
    children are still there and still trading: starting a second run for each
    would double every position, and neither run would know about the other.
    So a recorded process that is still alive is taken over rather than
    replaced, and the one that is gone is started.

    **A strategy that will not come back is left out of the record rather than
    retried for ever.** It is written to the log with the reason, and a trader
    presses Start when they have dealt with it.

    Nothing here raises. It runs at startup, and a worker that will not come up
    because one strategy could not be restored is worse than one that comes up
    and says so.
    """
    adopted = 0
    started = 0
    for run_id, held in all_running().items():
        try:
            pid = held.get("pid")
            if _process_is_alive(pid):
                if _adopt(run_id, int(pid)):
                    adopted += 1
                    continue
                # Alive, and this worker cannot confirm it is the run it was
                # told about. Starting one beside it is the outcome this whole
                # function exists to avoid, so nothing is started and a person
                # is told: two runs of one deployment double every position and
                # neither knows about the other.
                logger.error(
                    "%s is recorded as running under process %s, which is alive but is not that "
                    "run. Nothing was started for it, because a second run would double its "
                    "position. Check that process, then start the strategy again.",
                    run_id, pid,
                )
                continue

            ok, why = start_run(run_id)
            if ok:
                started += 1
            else:
                # Left out of the record: it is not running and nothing here is
                # going to make it run, so a trader pressing Start is the next
                # step rather than this trying again on every restart.
                mark_stopped(run_id)
                logger.warning("Could not put %s back after a restart: %s", run_id, why)
        except Exception:
            logger.exception("Could not restore the OpenScript run for %s", run_id)

    if adopted or started:
        logger.info(
            "Put back %d OpenScript run(s): %d already running and taken over, %d started",
            adopted + started, adopted, started,
        )
    return adopted, started


def _is_our_run(run_id: str, pid: int) -> bool:
    """Whether this process really is this deployment's run.

    **An id on its own proves nothing, and acting on one is dangerous.** Process
    ids are reused on every platform this runs on, and the gap between a worker
    dying and the next one starting is exactly when the operating system hands
    the number to somebody else. Adopting it would put an unrelated process into
    the registry, and the next Stop would terminate whatever it happened to be.

    So the command line is read and has to name both this runner and this
    deployment. The deployment and not the file, because a run carries its id on
    its own command line as ``--strategy-name``: matching the file alone would
    let one deployment of a script adopt another deployment of the same script,
    and the next Stop would then stop the wrong instrument. That is the same
    test the strategy host makes of its own children, sharpened by the one thing
    this has that it does not.

    **Unreadable is not the same as ours.** A process this worker may not
    inspect, or one whose command line has gone because it is a zombie, answers
    no: refusing to adopt costs a strategy that does not come back and says so,
    and adopting wrongly costs somebody else's process being killed.
    """
    try:
        words = psutil.Process(pid).cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error, OSError):
        return False
    except Exception:
        logger.exception("Could not read the command line of process %s", pid)
        return False

    if not words:
        return False
    written = " ".join(str(one) for one in words)
    return RUNNER_SCRIPT.name in written and run_id in written


def _adopt(run_id: str, pid: int) -> bool:
    """Take over a live child of a previous worker. True once it is registered.

    The log file is the one that process is already writing to, found rather
    than guessed: opening a new one would split a run's own account of itself
    across two files at the moment somebody most wants to read it.
    """
    if not _is_our_run(run_id, pid):
        return False

    saved = read_run_config(run_id) or {}
    script = str(saved.get("script") or "")
    logs = logs_for(run_id)

    with PROCESS_LOCK:
        _forget_finished_locked()
        if run_id in RUNNING_RUNS:
            return False
        RUNNING_RUNS[run_id] = {
            "process": Adopted(pid),
            "pid": pid,
            # The moment this worker took it over, which is not when the run
            # began. A row saying otherwise would claim a run had just started
            # every time the application was restarted.
            "started_at": _ist_now(),
            "log_file": str(logs[0]) if logs else None,
            "script": script,
            "symbol": saved.get("symbol", ""),
            "exchange": saved.get("exchange", ""),
            "interval": saved.get("interval", ""),
            "product": saved.get("product", ""),
        }

    logger.info("Took over the OpenScript run %s, already running as process %s", run_id, pid)
    return True


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
    interrupted: BaseException | None = None
    for run_id in ids:
        try:
            # Not forgotten: the worker is going down, which is not the
            # trader deciding this should stop. The next one puts it back.
            ok, _ = stop_run(run_id, forget=False)
        except Exception:
            logger.exception("An OpenScript run did not stop cleanly at exit")
            continue
        except BaseException as leaving:
            # **Not ``Exception``, and this is the whole point of the loop.**
            # ``SystemExit`` and ``KeyboardInterrupt`` are not ``Exception``, so
            # an ``except Exception`` here lets them out of the loop and
            # abandons every run after this one. That is not a tidiness
            # question: this function is what stops child processes that place
            # orders, a child outlives its parent, and the ones left behind keep
            # trading with nothing able to stop them.
            #
            # It arrives by an ordinary route. This is registered with
            # ``atexit``, so it runs while the interpreter is already leaving
            # after the first Ctrl+C. A second Ctrl+C while it is waiting for a
            # child lands the signal handler's ``SystemExit`` inside this loop,
            # which is exactly the impatient keypress somebody makes when a
            # shutdown seems slow. The wait it interrupts is the five seconds a
            # run is given to finish the bar it is on.
            #
            # So the signal is recorded and the remaining runs are still
            # stopped. Stopping them is the safety-critical half and it is
            # bounded; the exit is honoured immediately afterwards.
            logger.warning(
                "Interrupted while stopping OpenScript runs at exit; stopping the rest first"
            )
            if interrupted is None:
                interrupted = leaving
            continue
        if ok:
            stopped.append(run_id)

    if interrupted is not None:
        # Re-raised so a direct caller still exits the way it was told to. Under
        # ``atexit`` the interpreter prints that it ignored this, which is
        # noise; every child is gone by the time it does, which is the part that
        # matters.
        raise interrupted
    return stopped


def _stop_every_run_at_exit() -> None:
    """``stop_every_run`` for the way out of the interpreter.

    The only difference is the last step. ``stop_every_run`` re-raises an
    interrupt it caught, because a caller that asked to exit should exit and
    with the code it named. By the time this runs the exit code is already
    decided: the first signal's ``SystemExit`` set it and the interpreter is
    running its callbacks on the way out. Re-raising here cannot change it and
    can only print ``Exception ignored in atexit callback``, which reads like a
    crash during shutdown and hides the one line that says what happened.

    So the interrupt is logged and swallowed. What it was interrupting has
    already been finished by the time we get here, which is the part that
    matters: no child is left placing orders.
    """
    try:
        stop_every_run()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown was interrupted; every OpenScript run was stopped first")
    except Exception:
        logger.exception("Stopping the OpenScript runs at exit did not finish cleanly")


# Registered at import, which is what the strategy host does with its own, and
# for the same reason: the thing that must not be forgotten is the one that has to
# happen without anybody remembering to ask for it.
atexit.register(_stop_every_run_at_exit)
