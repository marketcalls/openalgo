"""Which strategies a trader means to have running, across a restart.

**The unit is a deployment, not a script.** One script deployed on two
instruments, or on one instrument at two intervals, is two runs with two
positions, so each is recorded and restored on its own. See
`openscript_deployment`.

**This records an intention, not a fact.** The fact is whether a process exists,
which the registry in ``openscript_runner_service`` holds and which dies with
the worker. What survives here is that somebody pressed Start and has not
pressed Stop: an application that is restarted, upgraded or that falls over
comes back and puts running strategies back, rather than leaving a trader to
discover at the close that nothing traded since lunchtime.

**So a clean exit does not clear it, and that is the whole design.** Stopping a
child on the way out is correct, because a child outlives its parent and one
left behind places orders with nothing able to stop it. But stopping the process
is not the trader changing their mind. Only Stop is, and only Stop clears this.

**The process id is kept beside it for one reason: not starting a second one.**
An application killed outright runs no exit handler, so its children are still
there and still trading. Coming back and starting a fresh run for each of them
would double every position, silently, at the worst possible moment. The id is
what lets the next worker recognise its predecessor's children and take them
over instead.

Written the way the rest of this folder writes: one file beside the scripts, in
the folder a container keeps on a named volume, through a temporary file and a
rename so an interrupted write cannot leave half of it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import pytz

from services.openscript_deployment import is_deployment_id
from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")

#: Beside the run settings and the schedules, for the same reason: a container
#: keeps this folder on a named volume, so what a trader started outlives an
#: upgrade.
STATE_FILE = Path("strategies") / "openscript_running.json"

# The same lock shape the run settings use, and for the same reason: a write is
# a read, a change and a rename, and two interleaved would lose one script's
# state. Ordinary rather than real, because every caller is a request greenlet
# or a scheduled job and a greenlet blocking on a real lock stops the worker.
_WRITE_LOCK = Lock()


def _now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def all_running() -> dict[str, dict[str, Any]]:
    """Every deployment a trader means to have running, by deployment id.

    An unreadable file answers the same as an absent one and says why in the
    log. The alternative is a worker that will not start over a state file,
    which is worse than one that starts having forgotten what was running.
    """
    try:
        text = STATE_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        logger.exception("Could not read the OpenScript running state at %s", STATE_FILE)
        return {}

    try:
        stored = json.loads(text)
    except ValueError:
        logger.exception("The OpenScript running state at %s does not read as JSON", STATE_FILE)
        return {}

    if not isinstance(stored, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for name, entry in stored.items():
        if not isinstance(name, str) or not isinstance(entry, dict) or not is_deployment_id(name):
            continue
        pid = entry.get("pid")
        out[name] = {
            "pid": pid if isinstance(pid, int) and pid > 0 else None,
            "since": str(entry.get("since") or ""),
        }
    return out


def mark_running(run_id: str, pid: int | None) -> None:
    """Record that this deployment is meant to be running, as this process id."""
    if not is_deployment_id(run_id):
        return
    _change(lambda held: held.update({run_id: {"pid": pid, "since": _now()}}))


def mark_stopped(run_id: str) -> None:
    """Record that a trader has stopped this deployment, so it does not come back."""
    if not is_deployment_id(run_id):
        return
    _change(lambda held: held.pop(run_id, None))


def _change(edit) -> None:
    """Read, change and write the file, all at once or not at all.

    Nothing raises. This is bookkeeping beside the act, and a start that worked
    must not be reported as a failure because a note about it could not be
    written: the run is there either way, and the log says what happened.
    """
    try:
        with _WRITE_LOCK:
            held = {name: dict(entry) for name, entry in all_running().items()}
            edit(held)
            _save(held)
    except Exception:
        logger.exception("Could not record the OpenScript running state")


def _save(state: dict[str, Any]) -> None:
    """Through a temporary file and a rename, so a kill cannot leave half of it."""
    temporary = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, default=str, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, STATE_FILE)
    except OSError:
        logger.exception("Could not save the OpenScript running state to %s", STATE_FILE)
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            logger.debug("The partial running state file could not be removed")
