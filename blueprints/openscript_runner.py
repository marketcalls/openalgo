"""OpenScript Runner Blueprint.

Routes: ``/openscript/runner``. Starts one saved OpenScript strategy, stops it,
reports which are running with their state and log location, and holds the
schedule that starts and stops one on its own.

**Starting answers with an identifier, never with a result.** The deployment
puts a five minute ceiling on a request and buffers the response on the main
path, so a route that waited for a run to finish would time out with the run
still going, and the caller would be told nothing about a strategy that is now
trading. So ``start`` hands back the identity of the run and a 202, and the
caller learns what happened by reading the status route and the log. This is a
property of the deployment, not a preference, and it is the one thing in this
file that must not be quietly relaxed.

**Nothing here decides where an order goes, and there is no switch to live.** A
strategy places orders the way every hosted strategy does: through the local
order API with the platform's own key, which reads the platform-wide analyzer
setting before anything else. That is the single place the destination is
decided, and a second switch here would be a second answer to a question that
must only have one. So the start route takes no options at all: a body that
carries one is refused rather than ignored, because a client that believes it
asked for something and was silently not given it is worse than a client that
was told no. Switching a strategy to live is a deliberate act by the operator
against the platform's own setting, and it stays there.

**One scheduler, and it is the one the strategy host already runs.** The
schedule below is registered on the scheduler ``blueprints.python_strategy``
starts, with that module's own trigger class and its own timezone object, taken
by attribute at call time rather than imported again here. A second scheduler in
the same worker would mean two objects firing jobs nobody can see together, and
the job identifiers are prefixed so the two sets can never collide.

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

import importlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from functools import partial
from pathlib import Path

import pytz
from flask import Blueprint, jsonify, request

import blueprints.openscript as openscript_sources
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

openscript_runner_bp = Blueprint("openscript_runner_bp", __name__, url_prefix="/openscript/runner")

# The same zone object the strategy host schedules against: the zone table hands
# back a cached instance per name, so this is that instance and not a copy of
# it. Used for the timestamps this module writes; the schedule itself is given
# the host's own attribute, so there is no way for the two to drift.
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

# The service that owns processes, and the names this module will call it by.
#
# It is written in parallel with this file, so each call is resolved by name at
# call time against a short list of the obvious spellings. This is a seam and
# not a design: once the names are settled, the lists collapse to one entry each
# and nothing else here changes.
_SERVICE_MODULE = "services.openscript_runner_service"
_START_NAMES = ("start", "start_strategy", "start_script", "start_run")
_STOP_NAMES = ("stop", "stop_strategy", "stop_script", "stop_run")
_STATUS_NAMES = ("status", "get_status", "running", "list_running")


class RunnerUnavailable(RuntimeError):
    """The runner service is absent, or answers to none of the names used here."""


# ---------------------------------------------------------------------------
# The service, and the shapes it may answer in
# ---------------------------------------------------------------------------


def _service():
    """The module that owns running processes, or None if it is not installed."""
    try:
        return importlib.import_module(_SERVICE_MODULE)
    except ImportError:
        return None


def _invoke(names, *args, **kwargs):
    """Call the first of ``names`` the service defines."""
    module = _service()
    if module is None:
        raise RunnerUnavailable("the runner service is not installed")
    for name in names:
        function = getattr(module, name, None)
        if callable(function):
            return function(*args, **kwargs)
    raise RunnerUnavailable(f"the runner service defines none of {names}")


def _answer(result):
    """Read what a service call came back with as ``(ok, detail)``.

    Three shapes are accepted because three are plausible and only one of them
    can be right: the ``(ok, message)`` pair the strategy host uses throughout,
    a dictionary, and a bare identifier. Anything else is read as success with
    no detail, which is the reading that does not invent a failure.
    """
    if isinstance(result, tuple) and len(result) == 2:
        ok, detail = result
        if isinstance(detail, dict):
            return bool(ok), detail
        return bool(ok), ({"message": str(detail)} if detail is not None else {})
    if isinstance(result, dict):
        marker = result.get("ok")
        if isinstance(marker, bool):
            return marker, result
        state = result.get("status")
        if isinstance(state, str):
            return state.strip().lower() not in ("error", "failed", "failure"), result
        return True, result
    if isinstance(result, str) and result:
        return True, {"id": result}
    if isinstance(result, bool):
        return result, {}
    return True, {}


def _identifier(detail, filename):
    """The identity of one run.

    The service's own identifier when it mints one. Otherwise the file name,
    which is a true identity here because a script has at most one run: the
    registry is keyed by script, so a second start is refused rather than
    producing a second run to tell apart.
    """
    for key in ("run_id", "id", "identifier", "run"):
        value = detail.get(key)
        if isinstance(value, str) and value:
            return value
    return filename


def _log_of(detail):
    """Where this run is writing, if the service said."""
    for key in ("log", "log_file", "logfile", "log_path"):
        value = detail.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _when(value):
    """A time as text, whatever the service keeps it as."""
    if isinstance(value, str) and value:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return None


def _message(detail, fallback):
    """The service's own sentence, or ours."""
    value = detail.get("message")
    return value if isinstance(value, str) and value else fallback


def _entry(name, info):
    """One running script, in the shape this route answers in."""
    return {
        "file": name,
        "id": _identifier(info, name),
        "state": str(info.get("state") or info.get("status") or "running"),
        "started_at": _when(info.get("started_at") or info.get("started")),
        "log": _log_of(info),
    }


def _entries(result):
    """Normalise whatever the service reports into a list of running entries."""
    if isinstance(result, tuple) and len(result) == 2:
        result = result[1]
    if isinstance(result, dict):
        inner = result.get("running")
        if isinstance(inner, (list, dict)):
            result = inner

    entries = []
    if isinstance(result, dict):
        for name, info in result.items():
            if isinstance(name, str):
                entries.append(_entry(name, info if isinstance(info, dict) else {}))
    elif isinstance(result, list):
        for info in result:
            if not isinstance(info, dict):
                continue
            name = (
                info.get("file") or info.get("filename") or info.get("script") or info.get("name")
            )
            if isinstance(name, str):
                entries.append(_entry(name, info))
    return sorted(entries, key=lambda item: item["file"])


def _running():
    """Every run the service is holding right now."""
    return _entries(_invoke(_STATUS_NAMES))


# ---------------------------------------------------------------------------
# The files a run needs
# ---------------------------------------------------------------------------


def _script_dir():
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


def _why_not_runnable(filename):
    """Why this script cannot be started, as ``(code, sentence)``, or None.

    Two states, and the second is the one worth a sentence of its own. A source
    with no compiled program beside it is saved, editable and openable, and
    nothing on this server will run it, which is a fact about the script rather
    than a fault in the request.
    """
    directory = _script_dir()
    if not (directory / filename).is_file():
        return 404, f"There is no script named {filename}."
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
        if isinstance(name, str) and SAFE_NAME.match(name) and isinstance(entry, dict)
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
    return importlib.import_module("blueprints.python_strategy")


def _scheduler(host):
    """The one scheduler, started if it has not been started yet."""
    host.init_scheduler()
    scheduler = host.SCHEDULER
    if scheduler is None:
        raise RunnerUnavailable("the platform scheduler is not running")
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
    """Put one script's start and stop on the scheduler.

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


def _is_trading_day(exchange):
    """Whether the exchange this script trades is open today.

    The strategy host already answers this, holidays, weekends and the
    occasional special session included, so it is asked rather than answered
    again. If it cannot be asked the schedule is honoured: a start on a closed
    day costs a strategy that finds no market, where refusing to start on a day
    that was open costs the session.
    """
    try:
        return _strategy_host().is_trading_day(exchange=exchange)
    except Exception:
        logger.exception("Could not check the trading calendar for %s", exchange)
        return True


def _scheduled_start(filename):
    """Start one script because its schedule said so.

    This runs on the scheduler and not in a request, so it raises nothing: an
    exception escaping here is a job the scheduler may stop running, and a
    schedule that silently stops is worse than one that logs a failure and fires
    again tomorrow.
    """
    try:
        entry = _load_schedules().get(filename)
        if entry is None:
            logger.info("No schedule left for %s, so it was not started", filename)
            return

        if not _is_trading_day(entry.get("exchange")):
            logger.info("%s was not started: the market is closed today", filename)
            return

        reason = _why_not_runnable(filename)
        if reason is not None:
            logger.warning("%s was not started: %s", filename, reason[1])
            return

        ok, detail = _answer(_invoke(_START_NAMES, filename))
        if ok:
            logger.info("Started %s on schedule, run %s", filename, _identifier(detail, filename))
        else:
            logger.warning(
                "%s did not start on schedule: %s",
                filename,
                _message(detail, "the runner refused it"),
            )
    except Exception:
        logger.exception("The scheduled start of %s failed", filename)


def _scheduled_stop(filename):
    """Stop one script because its schedule said so.

    Always attempted, whatever the calendar says and whether or not the script
    still looks runnable. A stop that is skipped leaves a position with nothing
    watching it, and stopping something that is already stopped costs nothing.
    """
    try:
        ok, detail = _answer(_invoke(_STOP_NAMES, filename))
        if ok:
            logger.info("Stopped %s on schedule", filename)
        else:
            logger.info(
                "%s was not stopped on schedule: %s",
                filename,
                _message(detail, "it was not running"),
            )
    except Exception:
        logger.exception("The scheduled stop of %s failed", filename)


def restore_schedules():
    """Put the stored schedules back on the scheduler, once.

    Cheap when there are none: the file is read, found empty, and the scheduler
    is never touched, so importing this module costs nothing on an installation
    that has never scheduled anything.
    """
    global _RESTORED
    if _RESTORED:
        return
    _RESTORED = True

    schedules = _load_schedules()
    if not schedules:
        return

    for filename, entry in schedules.items():
        try:
            _register_jobs(filename, entry)
        except Exception:
            logger.exception("Could not restore the schedule for %s", filename)
    logger.info("Restored %d OpenScript schedules", len(schedules))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _unavailable(error):
    """The answer when the part that owns processes is not there."""
    logger.warning("The OpenScript runner is unavailable: %s", error)
    return jsonify(
        {
            "status": "error",
            "message": (
                "This server cannot run OpenScript strategies yet. Nothing was started or stopped."
            ),
        }
    ), 503


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
    rather than as a comment. Where an order goes is the platform's own setting,
    read on the order path itself; a field here that appeared to choose it would
    be a second answer to that question, and a client that believed it had
    chosen and was ignored is the worst of the three outcomes.
    """
    if not SAFE_NAME.match(filename):
        return _refusal(filename)

    options = request.get_json(silent=True)
    if options is not None and (not isinstance(options, dict) or options):
        return jsonify(
            {
                "status": "error",
                "message": (
                    "Starting a script takes no options. Where its orders go is the "
                    "platform's own setting and is not chosen here."
                ),
            }
        ), 400

    reason = _why_not_runnable(filename)
    if reason is not None:
        code, sentence = reason
        return jsonify({"status": "error", "message": sentence}), code

    try:
        ok, detail = _answer(_invoke(_START_NAMES, filename))
    except RunnerUnavailable as error:
        return _unavailable(error)

    if not ok:
        return jsonify(
            {
                "status": "error",
                "message": _message(detail, f"{filename} could not be started."),
            }
        ), 409

    run = {
        "id": _identifier(detail, filename),
        "file": filename,
        "started_at": _when(detail.get("started_at")) or datetime.now(IST).isoformat(),
        "log": _log_of(detail),
    }
    logger.info("Starting OpenScript strategy %s as run %s", filename, run["id"])
    return jsonify(
        {
            "status": "success",
            "run": run,
            "message": f"{filename} is starting. Its log shows what it does next.",
        }
    ), 202


@openscript_runner_bp.route("/stop/<path:filename>", methods=["POST"])
@check_session_validity
def stop(filename):
    """Stop one running script.

    **A script that is not running is told so, and never told it was stopped.**
    An operator pressing stop believes something is running; answering success
    to that leaves them believing a strategy was taken off the market when
    nothing was. The check below is for the sentence, and the service's own
    answer is the truth: if it refuses after the check passed, its refusal is
    what comes back.
    """
    if not SAFE_NAME.match(filename):
        return _refusal(filename)

    try:
        if filename not in {entry["file"] for entry in _running()}:
            return jsonify({"status": "error", "message": f"{filename} is not running."}), 404

        ok, detail = _answer(_invoke(_STOP_NAMES, filename))
    except RunnerUnavailable as error:
        return _unavailable(error)

    if not ok:
        return jsonify(
            {
                "status": "error",
                "message": _message(detail, f"{filename} could not be stopped."),
            }
        ), 409

    logger.info("Stopped OpenScript strategy %s", filename)
    return jsonify(
        {
            "status": "success",
            "file": filename,
            "message": _message(detail, f"{filename} has been stopped."),
        }
    )


@openscript_runner_bp.route("/status", methods=["GET"], defaults={"filename": None})
@openscript_runner_bp.route("/status/<path:filename>", methods=["GET"])
@check_session_validity
def status(filename):
    """What is running, where it is writing, and what is scheduled.

    This is the route the caller of ``start`` comes back to. With no name it
    answers for every run; with one it answers for that script, and says so
    plainly when it is not running rather than answering with an empty list that
    reads the same as a runner that has stopped working.
    """
    restore_schedules()

    if filename is not None and not SAFE_NAME.match(filename):
        return _refusal(filename)

    try:
        running = _running()
    except RunnerUnavailable as error:
        return _unavailable(error)

    schedules = _load_schedules()
    logs = _logs_dir()

    if filename is None:
        return jsonify(
            {
                "status": "success",
                "running": running,
                "scheduled": [dict(entry, file=name) for name, entry in sorted(schedules.items())],
                "log_dir": logs,
            }
        )

    entry = next((item for item in running if item["file"] == filename), None)
    schedule = schedules.get(filename)
    return jsonify(
        {
            "status": "success",
            "file": filename,
            "run": entry,
            "running": entry is not None,
            "schedule": dict(schedule, file=filename) if schedule else None,
            "log_dir": logs,
        }
    )


@openscript_runner_bp.route("/schedule/<path:filename>", methods=["POST"])
@check_session_validity
def set_schedule(filename):
    """Set the times one script starts and stops, in IST.

    The body carries ``start_time`` and optionally ``stop_time``, ``days`` and
    ``exchange``. A field this route does not know is refused rather than
    ignored, for the reason the start route takes no body at all: a caller that
    thinks it configured something it did not is the failure worth preventing.

    The jobs go on before the schedule is stored, and the schedule is stored
    before the answer, so the two cannot disagree. If storing fails the jobs come
    straight back off, because a schedule that runs today and is gone after a
    restart is a schedule nobody can reason about.
    """
    if not SAFE_NAME.match(filename):
        return _refusal(filename)

    restore_schedules()

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(
            {"status": "error", "message": "Send a start time, as 24 hour HH:MM in IST."}
        ), 400

    allowed = {"start_time", "stop_time", "days", "exchange"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        return jsonify(
            {
                "status": "error",
                "message": (
                    "A schedule has a start time, a stop time, days and an exchange. "
                    f"This one also carried {', '.join(unknown)}."
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

    exchange = body.get("exchange")
    try:
        exchange = _strategy_host().normalize_exchange(exchange)
    except Exception:
        # Left as it came, or left unset. The default belongs to the host and
        # is not spelled a second time here: a schedule carrying no exchange is
        # normalised by the host on the day it fires.
        logger.exception("Could not read the exchange list")
        exchange = str(exchange).strip().upper() if exchange else None

    entry = {
        "start_time": start_time,
        "stop_time": stop_time,
        "days": days,
        "exchange": exchange,
    }

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
    if not SAFE_NAME.match(filename):
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
