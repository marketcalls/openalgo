"""
OpenScript Blueprint.

Stores and serves the trader's own OpenScript sources from
``strategies/openscript`` to the /trading chart, which compiles each one in the
browser and plots the result. Beside each source it stores the **compiled
program** that browser produced.

**Why the program is stored at all.** A ``.oscript`` file is source. The
compiler is TypeScript and the engine that will run a strategy on this server is
Python, deliberately without a compiler in it, and the production container
carries no JavaScript runtime. So there is exactly one place in the whole
deployment where a program can be compiled, and it is the page the trader is
already typing into. If the browser does not send the program, nothing server
side can ever run the script. That is the whole reason a save carries two things
rather than one.

**These are sources, not modules, and that is the whole difference from
``custom_indicators``.** A custom indicator is JavaScript the page imports and
runs, so whatever it contains executes with the page's own authority. An
OpenScript file is text that a compiler turns into a compiled program, which is
a list of instructions an engine walks. A script can only name what the
instruction set exposes, so it reaches no network, no storage and no part of the
object graph around it. Nothing here is ever executed as code, which is why this
route hands the browser ``text/plain`` and never a JavaScript MIME type: a
response the page could import would defeat the reason for the format.

The compiled program is held to the same rule, and it is the harder half,
because a program is the thing that will one day be handed to an engine. It is
stored as data, under a name ending ``.program.json``, and served as
``application/json``. This module never imports it, never evaluates it and never
builds anything callable out of it. A file this route wrote is read back by a
runner as bytes and handed to an engine that walks it.

That is also what lets it run under the deployment's content security policy
unchanged. ``csp.py`` sets ``script-src 'self' https://cdn.socket.io`` with no
``unsafe-eval``, so a design that built a function out of text would be refused
in the browser. Compiling to data needs no policy change, no new directive and
no exception.

**Why writes exist here and not in ``custom_indicators``.** A custom indicator
is authored in a desktop editor and dropped in a folder. An OpenScript study is
authored in /trading, so the page that writes it is the page that runs it.

The folder sits under ``strategies/`` for the reason the indicators folder does:
it is already the home for user authored content and is the path Docker keeps on
a named volume (``openalgo_strategies:/app/strategies``), so a trader's scripts
survive a container rebuild for free. Nothing here is committed, and an upgrade
leaves it alone.

No route, port or directive is added to the deployment's nginx configuration.
Everything below is under ``location /``, which already proxies to the
application, so a hosted install upgrades without a config migration.
"""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

openscript_bp = Blueprint("openscript_bp", __name__, url_prefix="/openscript")

SCRIPTS_DIR = Path("strategies") / "openscript"

# A served or saved filename must match this exactly. ``send_from_directory``
# already refuses to escape the directory, so this is the second layer: it keeps
# the route to plain sources and rejects anything with a path separator, a dot
# segment, or an extension this route does not own.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.oscript$")

# What a compiled program is called, appended to the source's own name.
#
# Derived from a name that has already been through ``_SAFE_NAME`` and never
# from anything a caller sent, so one check covers both files. No route here
# accepts a program name off the wire: a caller names the script, and this
# module names the file beside it. The suffix also keeps a program outside
# ``_SAFE_NAME``, so it can never be listed as a source, read through the source
# route, or written by one.
_PROGRAM_SUFFIX = ".program.json"

# The largest source this route will store.
#
# A script is kilobytes. The ceiling is here because the smallest deployment
# leaves nginx's request body limit at its 1 MB default, and a limit that is
# generous on one install and default on another is the default one. Refusing at
# 256 kB gives a reason a trader can read, where letting the body grow gives them
# a gateway error with no explanation in it.
MAX_SOURCE_BYTES = 256 * 1024

# The largest compiled program this route will store.
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


def _script_dir() -> Path:
    """The scripts directory, resolved against the app's working directory."""
    return SCRIPTS_DIR.resolve()


def _rejected(filename: str):
    """The one refusal used by every route, so they cannot drift apart."""
    return jsonify(
        {
            "status": "error",
            "message": (
                f"Invalid script name {filename!r}. A name is letters, digits, "
                "dot, dash or underscore, and ends in .oscript"
            ),
        }
    ), 400


def _normalised(text: str) -> str:
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


def _source_hash(text: str) -> str:
    """The identity a compiled program records for the source it came from.

    The same string the compiler writes into the program's ``source.hash``,
    which is what lets this module answer a question it has no compiler to
    answer: whether the program in front of it was compiled from the source in
    front of it.
    """
    digest = hashlib.sha256(_normalised(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _program_path(directory: Path, filename: str) -> Path:
    """The compiled program that belongs beside one source."""
    return directory / (filename + _PROGRAM_SUFFIX)


def _stage(directory: Path, payload: bytes) -> Path:
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


@openscript_bp.route("/index.json", methods=["GET"])
@check_session_validity
def index():
    """List the trader's scripts, with the size and modification time of each.

    ``mtime`` is returned for the same reason the indicators route returns it:
    the page caches what it has already fetched, and an edited script would go
    on plotting its previous version until a hard refresh. ``bytes`` is returned
    so the panel can show a script it will refuse to save before the trader
    writes another line into it.

    ``program`` says whether a compiled program is stored beside this source,
    which is the same question as whether anything on this server could run it.
    A runner reads it to find its work without opening every file, and a panel
    reads it to tell a trader which of their scripts are still half a thought.
    """
    directory = _script_dir()
    if not directory.is_dir():
        return jsonify([])

    scripts = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or not _SAFE_NAME.match(entry.name):
            continue
        try:
            stat = entry.stat()
        except OSError:
            # A file that vanished between listing and stat is not an error
            # worth failing the whole panel over.
            logger.exception("Could not stat OpenScript source %s", entry.name)
            continue
        scripts.append(
            {
                "file": entry.name,
                "mtime": int(stat.st_mtime),
                "bytes": stat.st_size,
                "program": _program_path(directory, entry.name).is_file(),
            }
        )
    return jsonify(scripts)


@openscript_bp.route("/program/<path:filename>", methods=["GET"])
@check_session_validity
def program(filename: str):
    """Serve the compiled program stored beside one source.

    ``filename`` names the source and not the program, because the source name
    is the one a caller knows and the one ``_SAFE_NAME`` covers. The file this
    reads is named from it here, after the check.

    A script with no program answers plainly rather than with an empty body,
    because it is a state with a meaning rather than an absence: the script is
    saved and it has never compiled cleanly, so nothing on this server will run
    it. See ``save`` below.
    """
    if not _SAFE_NAME.match(filename):
        return _rejected(filename)

    directory = _script_dir()
    if not _program_path(directory, filename).is_file():
        return jsonify(
            {
                "status": "error",
                "message": (
                    f"{filename} has no compiled program yet. Open it in the chart and "
                    "save it once the console shows no errors."
                ),
            }
        ), 404

    # A program is data and is served as data. This route hands back no
    # JavaScript type for the reason the source route hands back none: a
    # response the page could import would run with the page's own authority,
    # which is the whole thing compiling to a program avoids.
    return send_from_directory(
        directory,
        filename + _PROGRAM_SUFFIX,
        mimetype="application/json; charset=utf-8",
    )


@openscript_bp.route("/<path:filename>", methods=["GET"])
@check_session_validity
def source(filename: str):
    """Serve one script as plain text.

    The mimetype is deliberate. This is source for a compiler, never a module
    for the page to import, and handing back a JavaScript type would invite
    exactly the thing the compiled program format exists to avoid.
    """
    if not _SAFE_NAME.match(filename):
        return _rejected(filename)

    directory = _script_dir()
    if not directory.is_dir():
        return jsonify({"status": "error", "message": "No scripts directory"}), 404

    return send_from_directory(directory, filename, mimetype="text/plain; charset=utf-8")


@openscript_bp.route("/<path:filename>", methods=["POST"])
@check_session_validity
def save(filename: str):
    """Create or replace one script, and the compiled program beside it.

    The body carries ``source``, and may carry ``program``: the canonical text
    of the compiled program, exactly as the compiler in the browser encoded it.

    **The program is stored byte for byte and is never re-encoded here.** The
    canonical encoding is what a program's hash is taken over, and an engine
    that loads a program from text refuses text that is not that encoding. This
    module has no compiler and cannot produce those bytes; reading the JSON and
    writing it back out would produce different ones, and the stored program
    would then be refused at load for a difference this route introduced. The
    parse below is a check and not a step: what reaches the disk is the body's
    own bytes.

    **What this route can check, and what it cannot.** It cannot tell whether a
    program is correct, or whether it is the canonical encoding, or whether it
    means what the source says; verifying a program is the engine's work and the
    engine does it at load. It can check the one thing that matters most here. A
    program records the hash of the source it was compiled from, so a program
    built from different text is refused rather than stored. Without that check
    a client holding a stale editor buffer could leave a runner executing
    yesterday's strategy while the trader reads today's source.

    **A save with no program is not an error.** A script that does not compile
    is still written, because a trader saves a thought half finished and losing
    it is the worse outcome by a distance. What that state means afterwards is
    exact: a source with no program beside it is a script the chart can open and
    edit, and nothing on this server will run.

    **A save with no program deletes the program that was there.** This is the
    deliberate decision, and the shape of the problem forces it. The
    alternative, leaving the old program in place, produces the one state this
    route must never reach: a runner reading a compiled program that is not the
    program of the source stored beside it, running instructions the trader can
    no longer see the source of. Deleting costs a recompile, which is one save.
    Keeping costs a wrong trade.

    **The order the files are replaced in follows from that.** The program is
    removed before the source is replaced and written after it, so the only
    states a crash can leave behind are a source with the program that belongs
    to it, or a source with no program, which means not runnable and is never
    wrong. It can never leave new source beside an old program. Both files are
    written and flushed to temporaries before anything is removed, so the work
    that can fail happens while the previous save is still whole.

    The write is atomic for the reason it always was: the bytes go to a
    temporary file in the same directory and are then moved over the target, so
    a process that dies partway leaves the previous script intact rather than a
    truncated one. A trader who has just lost a chart to a crash should not also
    find the script that drew it cut in half.

    A backup of the source is kept beside it, which is what ``python_strategy``
    does for the same reason: the editor is the only copy. The program gets no
    backup, because it is not a copy of anything anybody wrote. It is derived
    from the source, and the source is what is kept.
    """
    if not _SAFE_NAME.match(filename):
        return _rejected(filename)

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("source"), str):
        return jsonify(
            {"status": "error", "message": "Send a JSON body with a 'source' string"}
        ), 400

    source_text = data["source"]
    encoded = source_text.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        return jsonify(
            {
                "status": "error",
                "message": (
                    f"This script is {len(encoded)} bytes and the limit is {MAX_SOURCE_BYTES}"
                ),
            }
        ), 413

    # Everything about the program is settled before a file is touched, so a
    # refusal leaves the previous save exactly as it was.
    program_text = data.get("program")
    program_bytes = None
    if program_text is not None:
        if not isinstance(program_text, str):
            return jsonify(
                {
                    "status": "error",
                    "message": (
                        "Send the compiled program as text, or leave it out to save the "
                        "script on its own."
                    ),
                }
            ), 400

        program_bytes = program_text.encode("utf-8")
        if len(program_bytes) > MAX_PROGRAM_BYTES:
            return jsonify(
                {
                    "status": "error",
                    "message": (
                        f"The compiled program for this script is {len(program_bytes)} "
                        f"bytes and the limit is {MAX_PROGRAM_BYTES}"
                    ),
                }
            ), 413

        # ``RecursionError`` alongside the parse failure, because JSON nested a
        # few thousand deep is not a compiled program either and the reader
        # reports it by running out of stack rather than by refusing. Production
        # is one worker and an uncaught one costs the request, so it is refused
        # here in the same sentence as anything else unreadable.
        try:
            parsed = json.loads(program_text)
        except (ValueError, RecursionError):
            return jsonify(
                {
                    "status": "error",
                    "message": (
                        "The compiled program that came with this script could not be "
                        "read. Save it again."
                    ),
                }
            ), 400

        stamp = parsed.get("source") if isinstance(parsed, dict) else None
        recorded = stamp.get("hash") if isinstance(stamp, dict) else None
        if not isinstance(recorded, str):
            return jsonify(
                {
                    "status": "error",
                    "message": (
                        "What came with this script is not a compiled program. Save it again."
                    ),
                }
            ), 400

        if recorded != _source_hash(source_text):
            return jsonify(
                {
                    "status": "error",
                    "message": (
                        "The compiled program that came with this script was built from "
                        "different text. Save it again."
                    ),
                }
            ), 400

    directory = _script_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.exception("Could not create the OpenScript directory")
        return jsonify(
            {"status": "error", "message": f"Could not create the scripts folder: {error}"}
        ), 500

    target = directory / filename
    program_target = _program_path(directory, filename)
    staged: list[Path] = []
    try:
        if target.exists():
            backup = target.with_name(target.name + ".bak")
            backup.write_bytes(target.read_bytes())

        source_temporary = _stage(directory, encoded)
        staged.append(source_temporary)
        program_temporary = None
        if program_bytes is not None:
            program_temporary = _stage(directory, program_bytes)
            staged.append(program_temporary)

        # The order from the docstring, in four lines. Nothing here writes
        # bytes: it is one unlink and two renames, so the window in which the
        # pair could disagree is as narrow as a filesystem allows, and every
        # state inside it is a source with no program.
        program_target.unlink(missing_ok=True)
        os.replace(source_temporary, target)
        staged.remove(source_temporary)
        if program_temporary is not None:
            os.replace(program_temporary, program_target)
            staged.remove(program_temporary)
    except OSError as error:
        logger.exception("Could not save OpenScript source %s", filename)
        return jsonify({"status": "error", "message": f"Could not save: {error}"}), 500
    finally:
        # Whatever is still staged was never renamed into place, so it is a
        # temporary file nobody will ever come back for.
        for leftover in staged:
            leftover.unlink(missing_ok=True)

    logger.info(
        "Saved OpenScript source %s (%d bytes, program %s)",
        filename,
        len(encoded),
        "stored" if program_bytes is not None else "none",
    )
    return jsonify(
        {
            "status": "success",
            "file": filename,
            "bytes": len(encoded),
            "mtime": int(target.stat().st_mtime),
            "program": program_bytes is not None,
        }
    )


@openscript_bp.route("/<path:filename>", methods=["DELETE"])
@check_session_validity
def remove(filename: str):
    """Delete one script, the backup taken of it, and its compiled program.

    All three, because a program left behind by a deleted script is a program
    with no source anybody can read, and it is the one file here that something
    might later pick up and run.

    Deleting a script that is not there answers the same way as deleting one
    that is, because the caller asked for it to be gone and it is.
    """
    if not _SAFE_NAME.match(filename):
        return _rejected(filename)

    directory = _script_dir()
    target = directory / filename
    try:
        target.unlink(missing_ok=True)
        target.with_name(target.name + ".bak").unlink(missing_ok=True)
        _program_path(directory, filename).unlink(missing_ok=True)
    except OSError as error:
        logger.exception("Could not delete OpenScript source %s", filename)
        return jsonify({"status": "error", "message": f"Could not delete: {error}"}), 500

    logger.info("Deleted OpenScript source %s", filename)
    return jsonify({"status": "success", "file": filename})
