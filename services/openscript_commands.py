"""What a trader has asked of a run that is still going.

**There are two ways to end a run and they are not the same thing.**

*Pause* ends the process and leaves the position exactly where it is. It is what
a trader wants when a strategy is misbehaving, when they want to change its
parameters, or when they are about to restart the server: the position is theirs
to manage, and the strategy stops deciding about it.

*Stop* closes what the run is holding and then ends the process. It is what a
trader wants when they are finished with a strategy for the day, and it is the
one that must never be pressed by accident, which is why the page asks first.

**Why a file rather than a signal.** The instruction has to reach a process this
one did not start in this worker, on Windows and on the others, and the two
signals a run already answers both mean "leave". A second one would have to be
`SIGUSR1`, which Windows does not have, and a run started by a previous worker
answers whatever the file says without anybody having to have kept a handle to
it. It sits beside the run settings and the running state, in the folder a
container keeps on a named volume, and is written through a temporary file and a
rename so an interrupted write cannot leave half of it.

**The instruction is removed by the parent and never by the child**, with one
exception the child names: an instruction it tried and could not carry out. Left
in place that would be attempted on every wake, sending a closing order a minute
for a position that is not closing.

**Nothing here is imported at module level from the rest of the platform.** Both
sides of this file are its readers, and one of them is a separate process with
its own working directory that deliberately does not attach to the platform's
logging: importing that here made the runner fail at startup before it had read
a single argument. So the logger is fetched when something has actually gone
wrong, which is the only time it is needed.
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

IST = pytz.timezone("Asia/Kolkata")


def _said(message: str) -> None:
    """Report a fault, without making the platform's logger an import of this.

    See the module note: the child that reads this file is a separate process
    that must not attach to the platform's logging. A fault that cannot even be
    reported is swallowed rather than raised, because this is bookkeeping beside
    an act and the act is the part that matters.
    """
    try:
        from utils.logging import get_logger

        get_logger(__name__).exception(message)
    except Exception:  # noqa: BLE001 - there is nowhere left to say it
        pass

#: Beside the run settings and the running state, for the same reason.
COMMAND_FILE = Path("strategies") / "openscript_commands.json"

#: The one instruction a run takes today. Named rather than implied, because a
#: child reading an instruction it does not recognise has to be able to ignore
#: it rather than guess.
CLOSE = "close"

_WRITE_LOCK = Lock()


def _now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def all_commands() -> dict[str, dict[str, Any]]:
    """Every instruction outstanding, by deployment id.

    An unreadable file answers the same as an absent one. A run that refused to
    go on because it could not read this would be a run holding a position with
    nothing able to stop it, which is worse than one that misses an instruction
    and says so on the next wake.
    """
    try:
        text = COMMAND_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        _said(f"Could not read the OpenScript commands at {COMMAND_FILE}")
        return {}

    try:
        stored = json.loads(text)
    except ValueError:
        _said(f"The OpenScript commands at {COMMAND_FILE} do not read as JSON")
        return {}

    if not isinstance(stored, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for name, entry in stored.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        if not is_deployment_id(name):
            continue
        out[name] = {"what": str(entry.get("what") or ""), "asked": str(entry.get("asked") or "")}
    return out


def command_for(run_id: str) -> str:
    """The instruction outstanding for this run, or an empty string."""
    return all_commands().get(run_id, {}).get("what", "")


def ask(run_id: str, what: str = CLOSE) -> None:
    """Record that this run has been asked to do something before it ends."""
    if not is_deployment_id(run_id) or what != CLOSE:
        return
    _change(lambda held: held.update({run_id: {"what": what, "asked": _now()}}))


def clear(run_id: str) -> None:
    """Forget the instruction for this run. The parent's job, never the child's."""
    if not is_deployment_id(run_id):
        return
    _change(lambda held: held.pop(run_id, None))


def _change(edit) -> None:
    """Read, change and write the file, all at once or not at all.

    Nothing raises. This is bookkeeping beside the act: a stop that worked must
    not be reported as a failure because a note about it could not be written.
    """
    try:
        with _WRITE_LOCK:
            held = {name: dict(entry) for name, entry in all_commands().items()}
            edit(held)
            _save(held)
    except Exception:
        _said("Could not record an OpenScript command")


def _save(state: dict[str, Any]) -> None:
    """Through a temporary file and a rename, so a kill cannot leave half of it."""
    temporary = COMMAND_FILE.with_suffix(COMMAND_FILE.suffix + ".tmp")
    try:
        COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, default=str, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, COMMAND_FILE)
    except OSError:
        _said(f"Could not save the OpenScript commands to {COMMAND_FILE}")
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            # Nothing to do about it, and nothing that depends on it.
            pass
