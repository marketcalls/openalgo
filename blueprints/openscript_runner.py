"""OpenScript Runner Blueprint.

Routes: ``/openscript/runner``. Starts one saved OpenScript strategy, stops it,
reports which are running with their state and log location, holds what each
script is run on, and holds the schedule that starts and stops one on its own.

**Every name this file calls is imported by name.** An earlier version of this
module reached the service through lists of plausible spellings and
``getattr``, on the theory that the two halves were being written in parallel
and the names would settle later. They did not settle: the list for reading
state matched nothing the service defines, so status and stop answered "this
server cannot run OpenScript strategies yet" forever and a running strategy
could not be stopped from the page that started it. The tests did not catch it
because they ran against a stand in whose method names matched the guesses
rather than the service. So the imports below are ordinary imports, and a name
that is not there is an error at startup, in the one place where it is cheap to
notice, rather than a route that is quietly dead.

**Starting answers with an identifier, never with a result.** The deployment
puts a five minute ceiling on a request and buffers the response on the main
path, so a route that waited for a run to finish would time out with the run
still going, and the caller would be told nothing about a strategy that is now
trading. So ``start`` hands back the identity of the run and a 202, and the
caller learns what happened by reading the status route and the log. This is a
property of the deployment, not a preference, and it is the one thing in this
file that must not be quietly relaxed.

**A start carries nothing.** What a script runs on is saved against that script
in ``services/openscript_run_config.py`` and read by the service when the run
begins. A start that carried the instrument would let a run started from a page
and a run started by a schedule differ by one typed character, and the
difference would first be visible as an order on something nobody meant to
trade. So the start route takes no body at all, and a body that carries one is
refused rather than ignored: a client that believes it asked for something and
was silently not given it is worse than a client that was told no. A script
with nothing saved against it is refused by name, in the sentence the settings
module writes, saying which of the instrument, the exchange and the interval is
missing.

**Nothing here decides where an order goes, and there is no switch to live.** A
strategy places orders the way every hosted strategy does: through the local
order API with the platform's own key, which reads the platform-wide analyzer
setting before anything else. That is the single place the destination is
decided, and a second switch here would be a second answer to a question that
must only have one. The settings route refuses a field it does not know, so a
caller that invents one is told, and there is deliberately no field anywhere
below that a caller could set to reach a live destination.

**One scheduler, and it is the one the strategy host already runs.** The
schedule below is registered on the scheduler ``blueprints.python_strategy``
starts, with that module's own trigger class and its own timezone object, taken
by attribute at call time rather than imported again here. That module is
imported inside the function rather than at the top of this file for one
reason: importing it starts the scheduler, and a module that is only sometimes
scheduled against should not pay for that on import. A second scheduler in the
same worker would mean two objects firing jobs nobody can see together, and the
job identifiers are prefixed so the two sets can never collide.

**What this module never does.** It does not open a process, hold a lock over
one, or keep a registry of runs: ``services.openscript_runner_service`` owns all
of that, and this file is the HTTP surface over it. Production is a single
cooperatively scheduled worker, so a route that waited for anything would stop
the whole platform for every user until it returned. Everything below is a
validation, a small file read, and one call into the service that returns at
once.

**A script with no compiled program cannot be started.** A saved OpenScript file
is a source plus the compiled program the browser produced beside it, and a
source with no program next to it means exactly one thing: nothing on this
server can run it. That is refused here with a sentence a trader can act on,
rather than handed to the service to fail on later.
"""

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from functools import partial
from pathlib import Path

import pytz
from flask import Blueprint, jsonify, request, session

import blueprints.openscript as openscript_sources
from services.openscript_deployment import is_deployment_id
from services.openscript_run_config import (
    PRODUCTS,
    all_run_configs,
    delete_run_config,
    is_script_name,
    read_run_config,
    require_run_config,
    write_run_config,
)
from services.openscript_runner_service import (
    _as_run_id,
    is_running,
    logs_for,
    reap_finished_runs,
    restore_runs,
    run_id_for,
    running_runs,
    start_run,
    status_of,
    stop_run,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

openscript_runner_bp = Blueprint("openscript_runner_bp", __name__, url_prefix="/openscript/runner")

# The same zone object the strategy host schedules against: the zone table hands
# back a cached instance per name, so this is that instance and not a copy of
# it. The schedule itself is given the host's own attribute, so there is no way
# for the two to drift.
IST = pytz.timezone("Asia/Kolkata")

# The days a schedule may name. Any day is allowed rather than weekdays only,
# because an exchange occasionally holds a session on a weekend and a schedule
# that cannot express it is a schedule somebody works around by hand.
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# A schedule time, in the 24 hour form the rest of the platform uses.
_TIME = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")

# The name rule for a script, borrowed from the route that stores them rather
# than copied. Two spellings of one rule is how a name this runner accepts
# becomes a name that route will not store, so there is deliberately only one,
# and it lives with the files.
SAFE_NAME = openscript_sources._SAFE_NAME


def _names_something(given: str) -> bool:
    """Whether a path segment names a script or a deployment of one.

    Both reach these routes. A trader's page names deployments, because that is
    what is started, stopped and tracked, and a caller holding only a file name
    still works while a script is deployed once.
    """
    return bool(SAFE_NAME.match(given or "")) or is_deployment_id(given or "")

# What a settings body may carry, and nothing else. The list is short on
# purpose: every field a run needs is here, and a field a caller invents is
# refused by name rather than dropped, which is what keeps an imagined switch to
# live from looking like it worked.
SETTINGS_FIELDS = ("symbol", "exchange", "interval", "product", "inputs", "deployment")

# The most logs one answer names. A script run every day for a year has that
# many files, and a status page needs the recent ones rather than all of them.
MAX_LOGS_REPORTED = 20

# Where a schedule survives a restart. Beside the strategy host's own
# configuration file and inside the folder the deployment keeps on a named
# volume, so a trader's schedule outlives a rebuild. It is this module's file
# alone; nothing else reads or writes it.
SCHEDULES_FILE = Path("strategies") / "openscript_runner_schedules.json"

# Writers of the file above. Requests write it and scheduled jobs only read it,
# and under the production server both of those are green while on the
# development server both are real, so neither world has one kind waiting on the
# other and a plain lock is the right one. The critical section is a parse, a
# dict update and one atomic rename.
_SCHEDULES_LOCK = threading.RLock()

# Set once the stored schedules have been put back on the scheduler. A module
# level flag rather than a call from the application factory, because this
# module is imported at startup and registering the jobs is the last thing it
# does.
_RESTORED = False


class SchedulerUnavailable(RuntimeError):
    """The platform scheduler is not running, so nothing can be scheduled on it."""


# ---------------------------------------------------------------------------
# The shapes this module answers in
# ---------------------------------------------------------------------------


def _when(value):
    """A moment as text, or nothing.

    The service keeps a started time as a datetime in IST. It is written out
    here rather than handed to the encoder, which would turn it into the format
    an HTTP header uses and lose the zone a trader reads it in.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _run_answer(info: dict) -> dict:
    """One run, as this route reports it.

    ``state`` is always running. The service drops a run whose process has gone
    before it copies anything out, so a finished run is absent from its answers
    entirely rather than present and marked finished, and reporting the state it
    carries would be reporting a constant. It is here because the page that
    reads this shows a state beside every strategy.
    """
    return {
        "id": info.get("run"),
        # The same two names a settings answer carries, for the same reason.
        # A run's id is its deployment's id: that is what a book is filtered on
        # and what tells two runs of one script apart.
        "deployment": info.get("run"),
        "file": info.get("script"),
        "state": "running",
        "symbol": info.get("symbol"),
        "exchange": info.get("exchange"),
        "interval": info.get("interval"),
        "product": info.get("product") or "",
        "pid": info.get("pid"),
        "started_at": _when(info.get("started_at")),
        "log": info.get("log_file"),
    }


def _settings_answer(name: str, entry: dict) -> dict:
    """One deployment's run settings, as this route reports them.

    **Both names are reported.** ``deployment`` is what is started, stopped,
    scheduled and asked for a book, because one script is deployed on several
    instruments and several intervals at once. ``file`` is the script it runs,
    which is what a trader reads and what the editor opens. A page given only
    the first could not name the strategy, and one given only the second could
    not tell two deployments apart.

    The owning user is not among them. It is stored so that a run started by a
    schedule, with nobody watching, can find the key it authenticates with, and
    it is not something the page that sets an instrument needs back.
    """
    return {
        "deployment": name,
        "file": entry.get("script") or name,
        "symbol": entry.get("symbol", ""),
        "exchange": entry.get("exchange", ""),
        "interval": entry.get("interval", ""),
        "product": entry.get("product", ""),
        "inputs": entry.get("inputs") or {},
        "updated_at": entry.get("updated_at"),
    }


def _log_names(run_id: str) -> list[str]:
    """The names of the recent logs one run has written, newest first."""
    try:
        return [one.name for one in logs_for(run_id)[:MAX_LOGS_REPORTED]]
    except Exception:
        # Broad on purpose. This is a convenience beside the answer, and a status
        # page that fails outright because a directory could not be listed tells
        # an operator nothing about the strategy they came to look at.
        logger.exception("Could not list the logs for the OpenScript run %s", run_id)
        return []


# ---------------------------------------------------------------------------
# The files a run needs
# ---------------------------------------------------------------------------


def _script_dir() -> Path:
    """The directory the source route stores scripts in, read at call time.

    Taken from that module rather than spelled again, so a directory moved there
    moves here with it.
    """
    return openscript_sources._script_dir()


def _refusal(filename):
    """The one refusal for a name this runner does not own."""
    return jsonify(
        {
            "status": "error",
            "message": (
                f"Invalid script name {filename!r}. A name is letters, digits, "
                "dot, dash or underscore, and ends in .oscript"
            ),
        }
    ), 400


def _script_of(given):
    """The file a name runs: itself for a script, the settings for a deployment.

    A deployment id is not a file name and cannot be turned back into one, since
    a long one ends in a digest. Read out of the settings instead, which is the
    one place that records which file a deployment runs.
    """
    if is_script_name(given):
        return given
    saved = read_run_config(given) or {}
    return str(saved.get("script") or "")


def _why_not_runnable(name):
    """Why this cannot be started, as ``(code, sentence)``, or None.

    Two states, and the second is the one worth a sentence of its own. A source
    with no compiled program beside it is saved, editable and openable, and
    nothing on this server will run it, which is a fact about the script rather
    than a fault in the request.

    ``name`` is a deployment or a script, so the file is resolved before it is
    looked for. Looking for a deployment id on disk answers "there is no script
    named openscript_turn_SYM_EXCH_1m", which names something the trader never
    typed and points them at a file that was never supposed to exist.

    What it is run on is deliberately not checked here. The service reads the
    saved settings itself and refuses by name when they are missing, and asking
    the same question twice in two places is how the two answers end up
    disagreeing about which one a trader has to fix.
    """
    filename = _script_of(name)
    directory = _script_dir()
    if not filename or not (directory / filename).is_file():
        return 404, f"There is no strategy saved for {name}."
    program = directory / (filename + openscript_sources._PROGRAM_SUFFIX)
    if not program.is_file():
        return 409, (
            f"{filename} has no compiled program yet. Open it in the chart and save it "
            "once the console shows no errors."
        )
    return None


# ---------------------------------------------------------------------------
# The schedule store
# ---------------------------------------------------------------------------


def _load_schedules():
    """Every stored schedule, keyed by script name.

    A name that would not be accepted on the wire is dropped on the way in, so a
    file edited by hand cannot introduce one through the back door.
    """
    try:
        raw = SCHEDULES_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        logger.exception("Could not read the OpenScript runner schedules")
        return {}

    try:
        stored = json.loads(raw)
    except ValueError:
        logger.exception("The OpenScript runner schedule file could not be read")
        return {}

    if not isinstance(stored, dict):
        return {}
    return {
        name: entry
        for name, entry in stored.items()
        if isinstance(name, str) and _names_something(name) and isinstance(entry, dict)
    }


def _save_schedules(schedules):
    """Replace the stored schedules atomically.

    The bytes go to a temporary file in the same directory and are then moved
    over the target, so a process that dies partway leaves the previous
    schedules whole rather than a truncated file that reads as none at all.
    """
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(schedules, indent=2, sort_keys=True).encode("utf-8")

    handle, temporary = tempfile.mkstemp(dir=str(SCHEDULES_FILE.parent), suffix=".partial")
    try:
        out = os.fdopen(handle, "wb")
    except BaseException:
        os.close(handle)
        Path(temporary).unlink(missing_ok=True)
        raise

    try:
        with out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, SCHEDULES_FILE)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# The schedule itself, on the platform's one scheduler
# ---------------------------------------------------------------------------


def _strategy_host():
    """The strategy host module, imported when it is first needed.

    Imported here rather than at the top of the file for one reason: it starts
    the scheduler as it loads, and a module that is only sometimes scheduled
    against should not pay for that on import. Everything the schedule needs is
    read off it by attribute, so the trigger class and the timezone are the
    host's own and cannot become a second copy.
    """
    import blueprints.python_strategy as strategy_host

    return strategy_host


def _scheduler(host):
    """The one scheduler, started if it has not been started yet."""
    host.init_scheduler()
    scheduler = host.SCHEDULER
    if scheduler is None:
        raise SchedulerUnavailable("the platform scheduler is not running")
    return scheduler


def _logs_dir():
    """Where a run writes, which is where every hosted strategy writes."""
    try:
        return str(_strategy_host().LOGS_DIR)
    except Exception:
        logger.exception("Could not read the strategy log directory")
        return None


def _job_ids(filename):
    """The two job identifiers for one script.

    Prefixed, so they cannot collide with the strategy host's own jobs for a
    strategy that happens to be named the same thing.
    """
    return f"openscript_start_{filename}", f"openscript_stop_{filename}"


def _remove_jobs(filename):
    """Take this script's jobs off the scheduler, if they are on it."""
    try:
        scheduler = _scheduler(_strategy_host())
    except Exception:
        logger.exception("Could not reach the scheduler to remove jobs for %s", filename)
        return
    for job_id in _job_ids(filename):
        try:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        except Exception:
            logger.exception("Could not remove scheduled job %s", job_id)


def _register_jobs(filename, entry):
    """Put one deployment's start and stop on the scheduler.

    The trigger class and the timezone come off the strategy host, so this is
    the same trigger, on the same scheduler, in the same zone as every other
    scheduled strategy on this server.
    """
    host = _strategy_host()
    scheduler = _scheduler(host)
    start_job, stop_job = _job_ids(filename)
    days = ",".join(entry["days"])

    hour, minute = (int(part) for part in entry["start_time"].split(":"))
    scheduler.add_job(
        func=partial(_scheduled_start, filename),
        trigger=host.CronTrigger(hour=hour, minute=minute, day_of_week=days, timezone=host.IST),
        id=start_job,
        replace_existing=True,
    )

    if entry.get("stop_time"):
        hour, minute = (int(part) for part in entry["stop_time"].split(":"))
        scheduler.add_job(
            func=partial(_scheduled_stop, filename),
            trigger=host.CronTrigger(hour=hour, minute=minute, day_of_week=days, timezone=host.IST),
            id=stop_job,
            replace_existing=True,
        )
    elif scheduler.get_job(stop_job):
        scheduler.remove_job(stop_job)


def _is_trading_day(filename):
    """Whether the exchange this script trades is open today.

    The exchange comes from the script's own run settings rather than from the
    schedule. It is already saved there, it is the one the orders will be sent
    to, and a second copy typed into a schedule is a second thing to keep in
    step: a trader moving a script from one venue to another would otherwise
    leave a schedule checking the calendar of a venue the script no longer
    touches.

    The strategy host already answers the calendar question, holidays, weekends
    and the occasional special session included, so it is asked rather than
    answered again. If it cannot be asked the schedule is honoured: a start on a
    closed day costs a strategy that finds no market, where refusing to start on
    a day that was open costs the session.
    """
    exchange = (read_run_config(filename) or {}).get("exchange") or ""
    try:
        host = _strategy_host()
        return host.is_trading_day(exchange=exchange) if exchange else host.is_trading_day()
    except Exception:
        logger.exception("Could not check the trading calendar for %s", filename)
        return True


def _scheduled_start(filename):
    """Start one script because its schedule said so.

    This runs on the scheduler and not in a request, so it raises nothing: an
    exception escaping here is a job the scheduler may stop running, and a
    schedule that silently stops is worse than one that logs a failure and fires
    again tomorrow.
    """
    try:
        if _load_schedules().get(filename) is None:
            logger.info("No schedule left for %s, so it was not started", filename)
            return

        if not _is_trading_day(filename):
            logger.info("%s was not started: the market is closed today", filename)
            return

        reason = _why_not_runnable(filename)
        if reason is not None:
            logger.warning("%s was not started: %s", filename, reason[1])
            return

        ok, message = start_run(filename)
        if ok:
            logger.info("Started %s on schedule: %s", filename, message)
        else:
            logger.warning("%s did not start on schedule: %s", filename, message)
    except Exception:
        logger.exception("The scheduled start of %s failed", filename)


def _scheduled_stop(filename):
    """Stop one script because its schedule said so.

    Always attempted, whatever the calendar says and whether or not the script
    still looks runnable. A stop that is skipped leaves a position with nothing
    watching it, and stopping something that is already stopped costs nothing.
    """
    try:
        ok, message = stop_run(filename)
        if ok:
            logger.info("Stopped %s on schedule: %s", filename, message)
        else:
            logger.info("%s was not stopped on schedule: %s", filename, message)
    except Exception:
        logger.exception("The scheduled stop of %s failed", filename)


#: How often finished runs are swept when nobody is looking at the page.
REAP_MINUTES = 5

#: The scheduler id the sweep is registered under.
REAP_JOB_ID = "openscript_reap_finished_runs"


def _reap_quietly():
    """The scheduled sweep. Never raises, because a job that raises is dropped."""
    try:
        gone = reap_finished_runs()
        if gone:
            logger.info("Swept %d finished OpenScript run(s): %s", len(gone), ", ".join(gone))
    except Exception:
        logger.exception("The OpenScript reaper failed; it will run again")


def restore_schedules():
    """Put the stored schedules back, and start the sweep that reaps finished runs.

    Cheap when there are no schedules: the file is read, found empty, and no job
    is registered for it. The reaper is registered either way, because a finished
    run has to be dropped from the registry whether or not anything is scheduled.

    **The flag is set at the end and not at the beginning.** It was set first,
    which meant the first attempt was the only attempt: a worker that imported
    this module before the platform scheduler was running burned it, every
    schedule failed into the log, and nothing tried again for the life of that
    worker, so a scheduled strategy simply never ran. Now a failure leaves the
    flag down and the next call retries.
    """
    global _RESTORED
    if _RESTORED:
        return

    schedules = _load_schedules()

    try:
        scheduler = _scheduler(_strategy_host())
    except Exception:
        # Without a scheduler there is nothing to restore onto, so leave the flag
        # down and let the next call try again.
        logger.exception("The platform scheduler is not available yet; will retry")
        return

    # Best effort, and deliberately not fatal. A run that is not swept is a stale
    # row that the next read of the registry clears anyway; a schedule that is not
    # restored is a strategy that silently never runs. The second is far worse, so
    # a failure here must not cost the restoration below.
    try:
        scheduler.add_job(
            _reap_quietly,
            "interval",
            minutes=REAP_MINUTES,
            id=REAP_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    except Exception:
        logger.exception(
            "Could not start the OpenScript reaper; finished runs are swept on the next "
            "read of the registry instead"
        )

    restored = 0
    for filename, entry in schedules.items():
        try:
            _register_jobs(filename, entry)
            restored += 1
        except Exception:
            logger.exception("Could not restore the schedule for %s", filename)

    # What a trader had running, put back. After the schedules, because a
    # strategy that is both scheduled and running should have its jobs in place
    # before it is started again, and before the flag below, so a failure here
    # still leaves the next call able to retry the whole restoration.
    try:
        # It says for itself what it put back, so nothing is logged twice here.
        restore_runs()
    except Exception:
        logger.exception("Could not put back the OpenScript runs after a restart")

    _RESTORED = True
    logger.info(
        "Restored %d of %d OpenScript schedules and started the reaper every %d minutes",
        restored, len(schedules), REAP_MINUTES,
    )


# ---------------------------------------------------------------------------
# Starting and stopping
# ---------------------------------------------------------------------------


@openscript_runner_bp.route("/start/<path:filename>", methods=["POST"])
@check_session_validity
def start(filename):
    """Start one script, and answer with the identity of the run.

    **The answer is an identifier and never a result.** The run outlives this
    request by design, so what comes back is what the caller needs in order to
    follow it: the run's identity, the file it is running, and the log it is
    writing to. Nothing in the response says what the strategy did, because at
    the moment it is written the strategy has not done anything yet.

    **The route takes no options.** A body carrying anything at all is refused,
    which is the boundary this file draws around live trading written as code
    rather than as a comment. What the script runs on is saved against it and
    read by the service; where its orders go is the platform's own setting, read
    on the order path itself. A field here that appeared to choose either would
    be a second answer to a settled question, and a client that believed it had
    chosen and was ignored is the worst of the three outcomes.
    """
    if not _names_something(filename):
        return _refusal(filename)

    options = request.get_json(silent=True)
    if options is not None and (not isinstance(options, dict) or options):
        return jsonify(
            {
                "status": "error",
                "message": (
                    "Starting a script takes no options. What it runs on is saved in its "
                    "run settings, and where its orders go is the platform's own setting."
                ),
            }
        ), 400

    reason = _why_not_runnable(filename)
    if reason is not None:
        code, sentence = reason
        return jsonify({"status": "error", "message": sentence}), code

    ok, message = start_run(filename)
    if not ok:
        return jsonify({"status": "error", "message": message}), 409

    # The deployment that was started, which is what the caller asked for when
    # it named one and what its single deployment is when it named a script.
    run_id = _as_run_id(filename)
    info = status_of(filename)
    if info is None:
        # It started and has already ended, which a script whose engine is
        # missing or whose program will not load does within the second. The
        # identity still comes back, because the caller's next move is the one
        # it would have been anyway: read the log.
        logger.info("The OpenScript strategy %s started and ended at once", filename)
        return jsonify(
            {
                "status": "success",
                "run": {
                    "id": run_id,
                    "deployment": run_id,
                    "file": filename,
                    "state": "finished",
                    "started_at": None,
                    "log": None,
                },
                "logs": _log_names(run_id),
                "message": f"{filename} started and has already ended. Its log says why.",
            }
        ), 202

    logger.info("Starting OpenScript strategy %s as run %s", filename, run_id)
    return jsonify(
        {
            "status": "success",
            "run": _run_answer(info),
            "message": f"{filename} is starting. Its log shows what it does next.",
        }
    ), 202


@openscript_runner_bp.route("/pause/<path:filename>", methods=["POST"])
@openscript_runner_bp.route("/stop/<path:filename>", methods=["POST"])
@check_session_validity
def pause(filename):
    """End one run and leave its position exactly where it is.

    **This is a pause and not a stop**, and the difference is the position. A
    trader pauses a strategy to change a parameter, to look at what it is doing,
    or before restarting the server: the position becomes theirs to manage and
    the strategy stops deciding about it. Closing it here would spend money the
    trader never asked to spend. The route that closes is below.

    ``/stop`` still reaches this, because it is what every caller written before
    the two were separated means and because that is the safer of the two to
    answer: a caller that meant to close and paused instead still holds its
    position, where a caller that meant to pause and closed instead has paid a
    spread and lost a position it wanted.

    **A run that is not running is told so, and never told it was stopped.** An
    operator pressing this believes something is running; answering success to
    that leaves them believing a strategy was taken off the market when nothing
    was. The check below is for the sentence, and the service's own answer is
    the truth: if it refuses after the check passed, its refusal is what comes
    back.
    """
    if not _names_something(filename):
        return _refusal(filename)

    if not is_running(filename):
        return jsonify({"status": "error", "message": f"{filename} is not running."}), 404

    ok, message = stop_run(filename)
    if not ok:
        return jsonify({"status": "error", "message": message}), 409

    logger.info("Paused OpenScript strategy %s", filename)
    return jsonify({"status": "success", "file": filename, "message": message})


@openscript_runner_bp.route("/close/<path:filename>", methods=["POST"])
@check_session_validity
def close(filename):
    """Close what one run is holding, then end it.

    **This one spends money**, so it is its own route rather than a flag on the
    one above: a caller that reaches the wrong route by accident should pause,
    which costs nothing, rather than close, which cannot be taken back. The page
    asks the trader before it calls this.

    **A close that did not happen is not reported as one.** The run stays
    running and holding, and the refusal says so and says what to do, because a
    trader told their position was closed when it was not will not look at it
    again.
    """
    if not _names_something(filename):
        return _refusal(filename)

    if not is_running(filename):
        return jsonify({"status": "error", "message": f"{filename} is not running."}), 404

    ok, message = stop_run(filename, close=True)
    if not ok:
        return jsonify({"status": "error", "message": message}), 409

    logger.info("Closed and stopped OpenScript strategy %s", filename)
    return jsonify({"status": "success", "file": filename, "message": message})


@openscript_runner_bp.route("/status", methods=["GET"], defaults={"filename": None})
@openscript_runner_bp.route("/status/<path:filename>", methods=["GET"])
@check_session_validity
def status(filename):
    """What is running, what it is running on, where it is writing, what is scheduled.

    This is the route the caller of ``start`` comes back to. With no name it
    answers for every run; with one it answers for that script, and says so
    plainly when it is not running rather than answering with an empty list that
    reads the same as a runner that has stopped working.
    """
    restore_schedules()

    if filename is not None and not _names_something(filename):
        return _refusal(filename)

    running = sorted(
        (_run_answer(info) for info in running_runs()),
        key=lambda item: item["file"] or "",
    )
    schedules = _load_schedules()
    logs = _logs_dir()

    if filename is None:
        settings = all_run_configs()
        return jsonify(
            {
                "status": "success",
                "running": running,
                "scheduled": [dict(entry, file=name) for name, entry in sorted(schedules.items())],
                "settings": [
                    _settings_answer(name, entry) for name, entry in sorted(settings.items())
                ],
                "log_dir": logs,
            }
        )

    entry = next((item for item in running if item["file"] == filename), None)
    schedule = schedules.get(filename)
    saved = read_run_config(filename)
    return jsonify(
        {
            "status": "success",
            "file": filename,
            "run": entry,
            "running": entry is not None,
            "schedule": dict(schedule, file=filename) if schedule else None,
            "settings": _settings_answer(filename, saved) if saved else None,
            "logs": _log_names(run_id_for(filename)),
            "log_dir": logs,
        }
    )


# ---------------------------------------------------------------------------
# What a script is run on
# ---------------------------------------------------------------------------


@openscript_runner_bp.route("/config", methods=["GET"])
@check_session_validity
def list_settings():
    """What every deployment is run on, ordered by the script each one runs."""
    stored = all_run_configs()
    return jsonify(
        {
            "status": "success",
            "settings": sorted(
                (_settings_answer(name, entry) for name, entry in stored.items()),
                # By the script a trader reads, then by where it runs, so two
                # deployments of one strategy sit together in the list.
                key=lambda one: (one["file"], one["symbol"], one["interval"]),
            ),
            "products": list(PRODUCTS),
        }
    )


@openscript_runner_bp.route("/config/<path:filename>", methods=["GET"])
@check_session_validity
def get_settings(filename):
    """What one script is run on.

    A script with nothing saved answers with the sentence a start would refuse
    it with, so the page asking the question and the run that would have failed
    say the same thing.
    """
    if not _names_something(filename):
        return _refusal(filename)

    saved = read_run_config(filename)
    if saved is None:
        _, why = require_run_config(filename)
        return jsonify({"status": "error", "message": why}), 404

    return jsonify(
        {
            "status": "success",
            "settings": _settings_answer(filename, saved),
            "products": list(PRODUCTS),
        }
    )


@openscript_runner_bp.route("/config/<path:filename>", methods=["POST"])
@check_session_validity
def set_settings(filename):
    """Save what one script is run on.

    The body carries the instrument, the exchange and the interval, optionally
    the product, and optionally the script's own parameters. A field this route
    does not know is refused rather than ignored, which is the rule that matters
    most here: this is the body a caller would invent a destination in, and
    being told no is the only answer that leaves them knowing where the
    destination is actually decided.

    **``deployment`` is what makes this an edit rather than a new one.** With it,
    the deployment keeps the id its orders are tagged with, so its own book stays
    its own. Without it, a new deployment is created with an id of its own, so a
    deployment made where another was removed does not inherit that one's orders,
    fills and position. Creating a second one on the same script, instrument and
    interval is refused by the settings store, because that is one strategy
    running twice on one instrument.

    The owning user is taken from the session and never from the body. It is
    stored so a run started by a schedule can find the key it authenticates
    with, and a body that could name somebody else would be a way to run a
    strategy as a user who did not ask for it.
    """
    if not SAFE_NAME.match(filename):
        return _refusal(filename)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(
            {
                "status": "error",
                "message": "Send the instrument, the exchange and the interval to run this on.",
            }
        ), 400

    unknown = sorted(set(body) - set(SETTINGS_FIELDS))
    if unknown:
        return jsonify(
            {
                "status": "error",
                "message": (
                    "Run settings are the instrument, the exchange, the interval, the "
                    "product and the script's own parameters. This one also carried "
                    f"{', '.join(unknown)}. Where a strategy's orders go is the platform's own "
                    "setting and is not chosen here."
                ),
            }
        ), 400

    for field in SETTINGS_FIELDS:
        if field == "inputs":
            continue
        value = body.get(field)
        if value is not None and not isinstance(value, str):
            return jsonify(
                {
                    "status": "error",
                    "message": f"Give the {field} as text, or leave it out.",
                }
            ), 400

    # The parameters are not text and are not checked here. What one may be is
    # decided once, where they are stored, because the same answer has to hold
    # for a file an operator edited by hand and for one this route wrote.
    if body.get("inputs") is not None and not isinstance(body.get("inputs"), dict):
        return jsonify(
            {
                "status": "error",
                "message": "Give the strategy parameters as a set of named values, or leave them out.",
            }
        ), 400

    ok, message = write_run_config(
        filename,
        symbol=body.get("symbol") or "",
        exchange=body.get("exchange") or "",
        interval=body.get("interval") or "",
        product=body.get("product") or "",
        user_id=session.get("user"),
        inputs=body.get("inputs"),
        deployment=body.get("deployment") or "",
    )
    if not ok:
        return jsonify({"status": "error", "message": message}), 400

    saved = read_run_config(filename) or {}
    logger.info("Saved the run settings for %s", filename)
    return jsonify(
        {
            "status": "success",
            "settings": _settings_answer(filename, saved),
            "message": message,
        }
    )


@openscript_runner_bp.route("/config/<path:filename>", methods=["DELETE"])
@check_session_validity
def clear_settings(filename):
    """Remove one deployment: what it runs on, and when it was to start.

    **A deployment that is running is not removed.** It used to be, leaving a
    process on the market whose settings had gone: the row could not be started
    again, its instrument was no longer recorded anywhere, and a trader who
    thought they had deleted a strategy had one still trading. Refusing is one
    sentence they can act on, and Pause and Stop are both one press away.

    **The schedule goes with it.** A deployment removed on its own left its
    start time on the scheduler, which then fired every morning for settings
    that were not there: a failure in a log, daily, for a strategy nobody
    believed existed any more.
    """
    if not _names_something(filename):
        return _refusal(filename)

    if read_run_config(filename) is None:
        return jsonify(
            {"status": "error", "message": f"{filename} has no run settings saved."}
        ), 404

    if is_running(filename):
        return jsonify(
            {
                "status": "error",
                "message": (
                    "This strategy is running, so it has not been removed. Pause it to keep its "
                    "position, or Stop it to close the position first, then remove it."
                ),
            }
        ), 409

    ok, message = delete_run_config(filename)
    if not ok:
        return jsonify({"status": "error", "message": message}), 500

    # After the settings and not before: a schedule with no settings behind it
    # is a job that fails, and settings with no schedule are simply a strategy
    # nobody has timed. If this half fails the log says so and the deployment is
    # still gone, which is what was asked for.
    _forget_schedule(filename)

    logger.info("Removed the OpenScript deployment %s", filename)
    return jsonify({"status": "success", "file": filename, "message": message})


def _forget_schedule(filename):
    """Take one deployment's start and stop off the scheduler and the file.

    Never raises. Removing a deployment is the act; this is the tidying beside
    it, and a scheduler that could not be reached must not turn a removal that
    happened into an error that says it did not.
    """
    try:
        _remove_jobs(filename)
        schedules = _load_schedules()
        if schedules.pop(filename, None) is not None:
            _save_schedules(schedules)
    except Exception:
        logger.exception("Could not remove the schedule for the deployment %s", filename)


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------


@openscript_runner_bp.route("/schedule/<path:filename>", methods=["POST"])
@check_session_validity
def set_schedule(filename):
    """Set the times one script starts and stops, in IST.

    The body carries ``start_time`` and optionally ``stop_time`` and ``days``.
    It does not carry an exchange: the calendar the schedule checks is the one
    the script's own run settings name, so there is one place a venue is typed
    and not two that can disagree.

    The jobs go on before the schedule is stored, and the schedule is stored
    before the answer, so the two cannot disagree. If storing fails the jobs come
    straight back off, because a schedule that runs today and is gone after a
    restart is a schedule nobody can reason about.
    """
    if not _names_something(filename):
        return _refusal(filename)

    restore_schedules()

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(
            {"status": "error", "message": "Send a start time, as 24 hour HH:MM in IST."}
        ), 400

    allowed = {"start_time", "stop_time", "days"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        return jsonify(
            {
                "status": "error",
                "message": (
                    "A schedule has a start time, a stop time and days. This one also "
                    f"carried {', '.join(unknown)}. The exchange comes from the script's "
                    "own run settings."
                ),
            }
        ), 400

    start_time = body.get("start_time")
    if not isinstance(start_time, str) or not _TIME.match(start_time):
        return jsonify(
            {"status": "error", "message": "Give a start time as 24 hour HH:MM in IST."}
        ), 400

    stop_time = body.get("stop_time")
    if stop_time is not None:
        if not isinstance(stop_time, str) or not _TIME.match(stop_time):
            return jsonify(
                {
                    "status": "error",
                    "message": "Give a stop time as 24 hour HH:MM in IST, or leave it out.",
                }
            ), 400
        if stop_time <= start_time:
            return jsonify(
                {
                    "status": "error",
                    "message": "The stop time is before the start time. Check both.",
                }
            ), 400

    days = body.get("days")
    if days is None:
        days = list(DAYS[:5])
    if not isinstance(days, list) or not days:
        return jsonify(
            {"status": "error", "message": "Give the days to run on, or leave them out."}
        ), 400
    days = [str(day).strip().lower() for day in days]
    unknown_days = sorted(set(days) - set(DAYS))
    if unknown_days:
        return jsonify(
            {
                "status": "error",
                "message": f"These are not days of the week: {', '.join(unknown_days)}.",
            }
        ), 400
    days = [day for day in DAYS if day in days]

    entry = {"start_time": start_time, "stop_time": stop_time, "days": days}

    try:
        _register_jobs(filename, entry)
    except Exception:
        # Its own sentence rather than the runner's, because nothing was asked
        # to start or stop here and saying so would send the reader looking in
        # the wrong place.
        logger.exception("Could not schedule %s", filename)
        return jsonify(
            {
                "status": "error",
                "message": (
                    "The schedule could not be set on this server right now. Nothing was changed."
                ),
            }
        ), 503

    try:
        with _SCHEDULES_LOCK:
            schedules = _load_schedules()
            schedules[filename] = entry
            _save_schedules(schedules)
    except OSError:
        logger.exception("Could not store the schedule for %s", filename)
        _remove_jobs(filename)
        return jsonify(
            {
                "status": "error",
                "message": (
                    "The schedule could not be saved, so it was not set. Check that the "
                    "strategies folder can be written to."
                ),
            }
        ), 500

    window = f"{start_time} IST" if not stop_time else f"{start_time} to {stop_time} IST"
    logger.info("Scheduled %s at %s on %s", filename, window, ", ".join(days))
    return jsonify(
        {
            "status": "success",
            "file": filename,
            "schedule": dict(entry, file=filename),
            "message": f"{filename} runs {window} on {', '.join(days)}.",
        }
    )


@openscript_runner_bp.route("/schedule/<path:filename>", methods=["DELETE"])
@check_session_validity
def clear_schedule(filename):
    """Remove one script's schedule.

    Removing a schedule that is not there answers the same way as removing one
    that is, because the caller asked for it to be gone and it is. Nothing
    running is touched: this stops the script being started again, and stopping
    the run in front of you is the stop route's job.
    """
    if not _names_something(filename):
        return _refusal(filename)

    restore_schedules()
    _remove_jobs(filename)

    try:
        with _SCHEDULES_LOCK:
            schedules = _load_schedules()
            if schedules.pop(filename, None) is not None:
                _save_schedules(schedules)
    except OSError:
        logger.exception("Could not remove the stored schedule for %s", filename)
        return jsonify(
            {
                "status": "error",
                "message": (
                    "The schedule was taken off the scheduler but could not be removed "
                    "from the saved schedules, so it will come back after a restart."
                ),
            }
        ), 500

    logger.info("Removed the schedule for %s", filename)
    return jsonify(
        {
            "status": "success",
            "file": filename,
            "message": f"{filename} is no longer scheduled.",
        }
    )


# Registered as this module loads, which is at startup, so a schedule set
# yesterday is on the scheduler before anybody asks for it. It reads one small
# file and returns without touching the scheduler when there is nothing stored.
try:
    restore_schedules()
except Exception:
    logger.exception("Could not restore the OpenScript schedules at startup")


# ---------------------------------------------------------------------------
# What one strategy has done
# ---------------------------------------------------------------------------


def _api_key():
    """The signed-in user's own API key, for the broker calls a book makes."""
    try:
        from flask import session

        from database.auth_db import get_api_key_for_tradingview

        user = session.get("user")
        return get_api_key_for_tradingview(user) if user else None
    except Exception:
        logger.exception("Could not read the API key for this session")
        return None


# ---------------------------------------------------------------------------
# What a trader picks from rather than types
# ---------------------------------------------------------------------------
#
# **A deployment names an instrument, an exchange, an interval and a product,
# and every one of them typed by hand is a run that fails later.** A symbol is
# the one string a broker mapping matches on, so a character wrong is a start
# refused a minute later in a log, or worse an instrument that exists and is not
# the one meant. An interval the broker does not serve is a run that fetches
# nothing. A product the exchange does not take is an order rejected at the
# broker, after a signal has been acted on.
#
# So the form offers what this platform already knows: the instrument master for
# the symbol, the broker's own interval list for the bar. Both are read through
# the platform's own services, which is where that knowledge already is.


@openscript_runner_bp.route("/instruments", methods=["GET"])
@check_session_validity
def instruments():
    """Instruments matching a query on one exchange, for the deployment form.

    Deliberately not restricted to a list of exchanges this blueprint keeps. A
    strategy runs on whatever the broker serves, and a second whitelist here
    would be a venue a trader can chart and backtest but not deploy on.
    """
    exchange = (request.args.get("exchange") or "").strip().upper()
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        # One character matches most of an exchange, which is a list nobody can
        # read. Answered as an empty result rather than a refusal: the box is
        # being typed into, and an error on every first keystroke is noise.
        return jsonify({"status": "success", "data": []})

    api_key = _api_key()
    if not api_key:
        return jsonify(
            {"status": "error", "message": "No API key for this session, so nothing can be searched."}
        ), 400

    from services.search_service import search_symbols

    _ok, response, code = search_symbols(query=query, exchange=exchange or None, api_key=api_key)
    return jsonify(response), code


@openscript_runner_bp.route("/intervals", methods=["GET"])
@check_session_validity
def intervals():
    """The bars this broker serves, for the deployment form.

    The broker's own answer rather than a list kept here. Offering a timeframe
    the broker does not serve is a deployment that saves, starts, and fetches no
    history at all.
    """
    api_key = _api_key()
    if not api_key:
        return jsonify(
            {"status": "error", "message": "No API key for this session, so the intervals are unknown."}
        ), 400

    from services.intervals_service import get_intervals_with_auth
    from services.strategy_module.order_dispatch import resolve_live_auth

    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return jsonify({"status": "error", "message": error}), 400

    _ok, response, code = get_intervals_with_auth(auth_token, broker)
    return jsonify(response), code


def _mode_for(filename):
    """Which book to read: the run's own side, never the platform's toggle.

    A run that is up is read from the side it started on, which the service
    noted when it started it. One that has stopped is read from the side it
    last traded on, which the run settings remember, because its orders are
    still the answer to what it did. With neither, the platform's current
    setting is all that is left, and a strategy that never ran has an empty
    book either way.

    Only the two words are taken. Anything else is not a side, and reading the
    live book because a value was not "sandbox" would be choosing a side
    nobody named.
    """
    from services.openscript_run_config import RUN_MODES, run_mode_of

    held = status_of(filename)
    if held and held.get("mode") in RUN_MODES:
        return str(held["mode"])

    recorded = run_mode_of(filename)
    if recorded:
        return recorded

    try:
        from database.settings_db import get_analyze_mode

        return "sandbox" if get_analyze_mode() else "live"
    except Exception:
        return "sandbox"


def _book(filename, which):
    """One of a strategy's three books, or the refusal that stopped it.

    The mode is the run's and not the platform's. A run that is up is read from
    the side it is trading on; one that has stopped is read from the side it
    last traded on, because its orders are still the answer to what it did. With
    neither, the platform's own setting is the only thing left to go on, and a
    strategy that never ran has an empty book either way.
    """
    if not _names_something(filename):
        return _refusal(filename)

    from services import openscript_books

    api_key = _api_key()
    if not api_key:
        return jsonify(
            {"status": "error", "message": "No API key for this session, so no book can be read."}
        ), 400

    # A book belongs to a deployment, because that is what an order's tag names.
    # A caller holding only a file name is resolved here, where the settings
    # are, so the books module stays a filter over rows and reads nothing.
    answer = which(_as_run_id(filename), api_key, _mode_for(filename))
    return jsonify(answer), (200 if answer.get("status") == "success" else 502)


@openscript_runner_bp.route("/orderbook/<filename>", methods=["GET"])
@check_session_validity
def orderbook(filename):
    """This strategy's orders, in the global orderbook's own envelope."""
    from services import openscript_books

    return _book(filename, openscript_books.orderbook)


@openscript_runner_bp.route("/tradebook/<filename>", methods=["GET"])
@check_session_validity
def tradebook(filename):
    """This strategy's fills."""
    from services import openscript_books

    return _book(filename, openscript_books.tradebook)


@openscript_runner_bp.route("/positions/<filename>", methods=["GET"])
@check_session_validity
def positions(filename):
    """The contracts this strategy traded, which is weaker than the other two.

    A position row is per contract and carries no strategy, so a row here may
    hold size another strategy or a manual order opened. The service says so in
    its own words and this route does not pretend otherwise.
    """
    from services import openscript_books

    return _book(filename, openscript_books.positions)
