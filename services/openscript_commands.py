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

**A close that worked is said so here, by the child, before it leaves.** The
parent cannot tell from the process alone: a run exits the same way after
closing its position as after being told to stop, and a run taken over from a
previous worker reports no exit status at all. So once its closing order has
filled (or it held nothing) the child turns its ``close`` into ``closed``, and
the parent reports a Stop as done only when it finds that. Anything else, after
the process has gone, is a close nobody can vouch for, and the trader is told
to check the position. ``closed`` is not an instruction: a run never acts on
it.

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
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
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

#: What the child writes over its ``close`` once the position is confirmed
#: closed, for the parent to read after the process has gone. Never acted on.
CLOSED = "closed"

_WRITE_LOCK = Lock()


def _now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


#: How often a read that the file system refused is tried before it counts as
#: unreadable. On Windows a read can be refused while another process renames
#: its write into place, which lasts a moment.
_READ_TRIES = 3
_READ_RETRY_SECONDS = 0.02


def _read_entries() -> dict[str, Any] | None:
    """The stored entries as they are on disk, ``{}`` when there is no file.

    None when the file is there and could not be read, which is not the same
    as it holding nothing: a change made from that would write every other
    run's instruction away. A file that reads but does not parse is corrupt
    rather than busy, since every write lands through a rename, and answers
    ``{}`` so the next change writes a good one over it.
    """
    text = ""
    for attempt in range(_READ_TRIES):
        try:
            text = COMMAND_FILE.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return {}
        except OSError:
            if attempt + 1 == _READ_TRIES:
                _said(f"Could not read the OpenScript commands at {COMMAND_FILE}")
                return None
            time.sleep(_READ_RETRY_SECONDS)

    try:
        stored = json.loads(text)
    except ValueError:
        _said(f"The OpenScript commands at {COMMAND_FILE} do not read as JSON")
        return {}
    return stored if isinstance(stored, dict) else {}


def all_commands() -> dict[str, dict[str, Any]]:
    """Every instruction outstanding, by deployment id.

    An unreadable file answers the same as an absent one. A run that refused to
    go on because it could not read this would be a run holding a position with
    nothing able to stop it, which is worse than one that misses an instruction
    and says so on the next wake.
    """
    return _recognised(_read_entries() or {})


def _recognised(stored: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The instructions among the stored entries that this module wrote."""
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


def record_closed(run_id: str) -> None:
    """The child's word that its close is done: ``close`` becomes ``closed``.

    Only an outstanding ``close`` is changed. An entry the parent has already
    cleared (it stopped waiting) is left gone rather than written back, so no
    instruction outlives the Stop that asked for it.
    """
    if not is_deployment_id(run_id):
        return

    def mark(held: dict[str, dict[str, Any]]) -> None:
        entry = held.get(run_id)
        if entry is not None and entry.get("what") == CLOSE:
            entry["what"] = CLOSED

    _change(mark)


def close_confirmed(run_id: str) -> bool:
    """Whether this run said its close is done. The parent asks once the run has gone."""
    return command_for(run_id) == CLOSED


#: How long a change waits for another process to finish its own, and how
#: often it looks. A change takes milliseconds, so this is only ever reached by
#: a process that is stuck, and then the change goes ahead as it always did.
_LOCK_WAIT_SECONDS = 2.0
_LOCK_POLL_SECONDS = 0.01

if os.name == "nt":
    import msvcrt

    def _try_lock(handle) -> bool:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(handle) -> None:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _try_lock(handle) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(handle) -> None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextmanager
def _across_processes() -> Iterator[bool]:
    """Hold the lock every process takes around a change to the file.

    The platform and every run change this file, each from its own process, and
    a change is a read, an edit and a write: two that overlap each write what
    they read, and one of the two edits is lost. A lost ``closed`` reports a
    Stop that worked as unconfirmed, and a lost ``close`` leaves a Stop waiting
    out its whole timeout.

    The lock is a sidecar file, taken without blocking and asked for again
    every few milliseconds, so a wait here never holds up anything else in the
    process that waits. The operating system releases it when the process
    holding it ends, so a run killed during a change cannot leave it held.

    Yields:
        True while it is held. False when it could not be taken in time; the
        change then goes ahead without it, as every change did before.
    """
    handle = None
    held = False
    try:
        try:
            path = COMMAND_FILE.with_name(f"{COMMAND_FILE.name}.lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "a+b")  # noqa: SIM115 - closed below, on every path
            until = time.monotonic() + _LOCK_WAIT_SECONDS
            while True:
                held = _try_lock(handle)
                if held or time.monotonic() >= until:
                    break
                time.sleep(_LOCK_POLL_SECONDS)
        except OSError:
            held = False
        yield held
    finally:
        if handle is not None:
            if held:
                _unlock(handle)
            handle.close()


def _change(edit) -> None:
    """Read, change and write the file, all at once or not at all.

    Held under a lock every process takes (``_across_processes``), so a change
    made by one process is never written over by another that read the file
    before it. A file that is there and could not be read is left alone rather
    than replaced by one holding nothing, and a change that changes nothing is
    not written.

    Nothing raises. This is bookkeeping beside the act: a stop that worked must
    not be reported as a failure because a note about it could not be written.
    """
    try:
        with _WRITE_LOCK, _across_processes() as locked:
            if not locked:
                _said(f"Changing {COMMAND_FILE} without the lock another process holds")
            stored = _read_entries()
            if stored is None:
                return
            held = {name: dict(entry) for name, entry in _recognised(stored).items()}
            before = json.dumps(held, sort_keys=True, default=str)
            edit(held)
            if json.dumps(held, sort_keys=True, default=str) == before:
                return
            _save(held)
    except Exception:
        _said("Could not record an OpenScript command")


def _save(state: dict[str, Any]) -> None:
    """Through a temporary file and a rename, so a kill cannot leave half of it.

    The temporary file is named for this write alone. Both the platform and
    every run write this file, from different processes, and the write lock
    only serialises writers inside one of them: through one shared temporary
    path, one writer's rename could publish the other's half written bytes, or
    fail, and a lost "close" left a Stop waiting out its whole timeout.
    """
    temporary = COMMAND_FILE.with_name(f"{COMMAND_FILE.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, default=str, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, COMMAND_FILE)
    except OSError:
        _said(f"Could not save the OpenScript commands to {COMMAND_FILE}")
    finally:
        # Gone already after a successful rename. On any failure it is a file
        # of this write alone that nothing will come back for.
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            # Nothing to do about it, and nothing that depends on it.
            pass
