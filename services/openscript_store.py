"""Where a trader's OpenScript sources live, and the one sequence that writes them.

Two callers write a script: the /trading editor through ``blueprints/openscript.py``
and the agent through ``services/agent/tools/openscript_gen.py``. Both go through
:func:`write_script`, so there is exactly one implementation of the replace
sequence, one name rule, one size limit and one per-file lock. Two copies of a
sequence whose whole point is keeping a source and its compiled program in step
is how a runner ends up executing a program built from different text.

**What is stored.** ``<name>.oscript`` is the source. ``<name>.oscript.program.json``
beside it is the compiled program, which only the browser can produce: the
compiler is TypeScript, production carries no JavaScript runtime, and this
server has no compiler. A source with no program is legitimate and means "opens
in the editor, will not run". The blueprint's ``save`` docstring is the long
form of why a save without a program deletes the one that was there.

**Threading.** :data:`FILE_LOCKS` holds stdlib locks, which are green under
eventlet. A real OS thread (the agent's) must reach :func:`write_script` through
``utils.real_threading.run_on_hub``, never directly. See ``utils/keyed_locks.py``.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from utils.keyed_locks import KeyedLocks
from utils.logging import get_logger

logger = get_logger(__name__)

#: The scripts folder, relative to the app's working directory. Under
#: ``strategies/`` because that is the home for user authored content and the
#: path Docker keeps on a named volume, so scripts survive a container rebuild.
SCRIPTS_DIR = Path("strategies") / "openscript"

#: A stored filename must match this exactly. It keeps the folder to plain
#: sources and rejects anything with a path separator, a dot segment, or an
#: extension this store does not own.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.oscript$")

# What a compiled program is called, appended to the source's own name.
#
# Derived from a name that has already been through ``SAFE_NAME`` and never
# from anything a caller sent, so one check covers both files. No route accepts
# a program name off the wire: a caller names the script, and this module names
# the file beside it. The suffix also keeps a program outside ``SAFE_NAME``, so
# it can never be listed as a source, read through the source route, or written
# by one.
PROGRAM_SUFFIX = ".program.json"

# The largest source this store will write.
#
# A script is kilobytes. The ceiling is here because the smallest deployment
# leaves nginx's request body limit at its 1 MB default, and a limit that is
# generous on one install and default on another is the default one. Refusing at
# 256 kB gives a reason a trader can read, where letting the body grow gives them
# a gateway error with no explanation in it.
MAX_SOURCE_BYTES = 256 * 1024

# The largest compiled program this store will write.
#
# A program runs several times the size of the source it came from, because the
# instruction list, the constant pool and the debug table are all written out:
# measured over the scripts in this folder, a 5.4 kB source compiles to 14 kB
# and a 240 byte one to 2.8 kB. The number is set against the same 1 MB request
# body the source limit is set against, and the two travel in one body: 256 kB
# of source and 512 kB of program, each grown by the escaping that carrying them
# as JSON strings costs, still fits under a default install. A script large
# enough to reach this has a problem no limit here can fix.
#
# It is a latency ceiling as well as a size one. Production is a single
# cooperatively scheduled worker and the bytes below are written and flushed to
# the disk inside the request, so this bounds how long one save can hold it.
MAX_PROGRAM_BYTES = 512 * 1024

# One save or delete of a given script at a time. The replace sequence below
# (backup, stage, remove the program, replace the source, replace the program)
# only keeps a source and its program in step while nothing else runs it for
# the same file: two saves interleaved could leave source B beside program A,
# and a deployed strategy would run A while the editor showed B. Under the
# eventlet worker local file operations never yield, so this is never
# contended there; under gthread and on the development server it serialises
# the sequence. Keyed by file name, so different scripts do not wait on each
# other, and forgotten once no save of that file is in flight.
FILE_LOCKS = KeyedLocks(name="openscript-files")


@dataclass(frozen=True)
class SavedScript:
    """What one completed write left on disk.

    Attributes:
        file: The script's filename.
        path: The source file written.
        bytes: Size of the source in bytes.
        program: True when a compiled program was written beside it.
        replaced: True when a script of that name existed and was backed up.
    """

    file: str
    path: Path
    bytes: int
    program: bool
    replaced: bool


class ScriptConflict(Exception):
    """A save refused because of what is already stored under that name.

    Raised only when the caller asked :func:`write_script` not to replace, so
    the /trading save route, which always replaces, never sees it.

    Attributes:
        filename: The script's name.
        compiled: True when a compiled program sits beside the name, which
            means the /trading editor saved it and a deployment may run it.
    """

    def __init__(self, filename: str, compiled: bool) -> None:
        detail = "a compiled program" if compiled else "a source"
        super().__init__(f"{filename} already has {detail} stored")
        self.filename = filename
        self.compiled = compiled


def script_dir() -> Path:
    """The scripts directory, resolved against the app's working directory."""
    return SCRIPTS_DIR.resolve()


def normalised(text: str) -> str:
    """The source text in the language's own normal form.

    Two rules, both the language's rather than this module's: a leading byte
    order mark is not part of the text, and a carriage return before a newline
    is not part of it either. The compiler applies these before it does anything
    else, so the hash it stamps into a program is taken over the result. A
    second, slightly different spelling of the rule here would make every save
    that carries a program look like a mismatch, so it is held to exactly those
    two rules and nothing else.
    """
    without_mark = text[1:] if text.startswith("\ufeff") else text
    return without_mark.replace("\r\n", "\n")


def source_hash(text: str) -> str:
    """The identity a compiled program records for the source it came from.

    The same string the compiler writes into the program's ``source.hash``,
    which is what lets this module answer a question it has no compiler to
    answer: whether the program in front of it was compiled from the source in
    front of it.
    """
    digest = hashlib.sha256(normalised(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def program_path(directory: Path, filename: str) -> Path:
    """The compiled program that belongs beside one source."""
    return directory / (filename + PROGRAM_SUFFIX)


def backup_path(directory: Path, filename: str) -> Path:
    """The backup kept of a source when a save replaces it."""
    return directory / (filename + ".bak")


def stage(directory: Path, payload: bytes) -> Path:
    """Write bytes to a temporary file in the same directory and hand it back.

    Same directory, so the move that follows is a rename rather than a copy
    across filesystems, which is what makes it atomic. The caller does the
    renaming; this does the part that can fail, which is getting the bytes onto
    the disk.
    """
    handle, temporary = tempfile.mkstemp(dir=str(directory), suffix=".partial")
    try:
        # `mkstemp` hands back a raw descriptor, and production is a single
        # worker that never restarts, so one leaked on a failure path stays
        # leaked for the life of the process. Wrapping it before the try that
        # unlinks means the wrapper owns it from here: `fdopen` either takes the
        # descriptor and closes it, or raises without taking it, which is the
        # one case the bare close below covers.
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
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise

    return Path(temporary)


def write_script(
    directory: Path,
    filename: str,
    source: bytes,
    program: bytes | None = None,
    *,
    replace: bool = True,
    replace_compiled: bool = True,
) -> SavedScript:
    """Create or replace one script, and the compiled program beside it.

    The caller has already checked ``filename`` against :data:`SAFE_NAME`, the
    sizes against :data:`MAX_SOURCE_BYTES` and :data:`MAX_PROGRAM_BYTES`, that
    ``program`` records the hash of ``source``, and that ``directory`` exists.
    This is the write and nothing else.

    **A write with no program deletes the program that was there**, so the only
    states a crash can leave behind are a source with the program that belongs
    to it, or a source with no program, which means not runnable and is never
    wrong. The program is removed before the source is replaced and written
    after it. Both files are written and flushed to temporaries before anything
    is removed, so the work that can fail happens while the previous save is
    still whole, and each move is a rename within one directory, so a process
    that dies partway leaves the previous script intact rather than truncated.

    A backup of the source is kept beside it, because the editor is the only
    copy. The program gets no backup: it is derived from the source.

    The two ``replace`` flags are checked under the same per-file lock as the
    write, so a save from /trading cannot slip a program in between the check
    and the replace.

    Args:
        directory: The scripts directory, already created.
        filename: The script's name, already checked against :data:`SAFE_NAME`.
        source: The source text, UTF-8 encoded.
        program: The compiled program's canonical text, UTF-8 encoded and
            stored byte for byte, or None to store the source on its own.
        replace: False to refuse when a source of that name already exists.
        replace_compiled: False to refuse when a compiled program of that name
            exists, whatever ``replace`` says.

    Returns:
        What was written.

    Raises:
        ScriptConflict: A flag refused the save. Nothing was written.
        OSError: The write failed. Whatever was staged has been removed and the
            previous save is untouched, except that a removed program stays
            removed, which is the safe direction.
    """
    target = directory / filename
    program_target = program_path(directory, filename)
    staged: list[Path] = []
    replaced = False
    try:
        with FILE_LOCKS.hold(filename):
            if not replace_compiled and program_target.exists():
                raise ScriptConflict(filename, compiled=True)
            if not replace and target.exists():
                raise ScriptConflict(filename, compiled=False)
            if target.exists():
                replaced = True
                backup_path(directory, filename).write_bytes(target.read_bytes())

            source_temporary = stage(directory, source)
            staged.append(source_temporary)
            program_temporary = None
            if program is not None:
                program_temporary = stage(directory, program)
                staged.append(program_temporary)

            # The order from the docstring, in four lines. Nothing here writes
            # bytes: it is one unlink and two renames, so the window in which
            # the pair could disagree is as narrow as a filesystem allows, and
            # every state inside it is a source with no program.
            program_target.unlink(missing_ok=True)
            os.replace(source_temporary, target)
            staged.remove(source_temporary)
            if program_temporary is not None:
                os.replace(program_temporary, program_target)
                staged.remove(program_temporary)
    finally:
        # Whatever is still staged was never renamed into place, so it is a
        # temporary file nobody will ever come back for.
        for leftover in staged:
            leftover.unlink(missing_ok=True)

    logger.info(
        "Saved OpenScript source %s (%d bytes, program %s)",
        filename,
        len(source),
        "stored" if program is not None else "none",
    )
    return SavedScript(
        file=filename,
        path=target,
        bytes=len(source),
        program=program is not None,
        replaced=replaced,
    )


def list_scripts(directory: Path) -> list[dict]:
    """Describe every source in the scripts directory.

    Args:
        directory: The scripts directory. A missing one lists nothing.

    Returns:
        One ``{"file", "mtime", "bytes", "program"}`` entry per source, sorted
        by name. ``program`` says whether a compiled program is stored beside
        it, which is the same question as whether anything on this server could
        run it.
    """
    if not directory.is_dir():
        return []

    scripts = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or not SAFE_NAME.match(entry.name):
            continue
        try:
            stat = entry.stat()
        except OSError:
            # A file that vanished between listing and stat is not an error
            # worth failing the whole list over.
            logger.exception("Could not stat OpenScript source %s", entry.name)
            continue
        scripts.append(
            {
                "file": entry.name,
                "mtime": int(stat.st_mtime),
                "bytes": stat.st_size,
                "program": program_path(directory, entry.name).is_file(),
            }
        )
    return scripts
