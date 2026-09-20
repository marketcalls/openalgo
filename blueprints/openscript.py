"""
OpenScript Blueprint.

Stores and serves the trader's own OpenScript sources from
``strategies/openscript`` to the /trading chart, which compiles each one in the
browser and plots the result.

**These are sources, not modules, and that is the whole difference from
``custom_indicators``.** A custom indicator is JavaScript the page imports and
runs, so whatever it contains executes with the page's own authority. An
OpenScript file is text that a compiler turns into a compiled program, which is
a list of instructions an engine walks. A script can only name what the
instruction set exposes, so it reaches no network, no storage and no part of the
object graph around it. Nothing here is ever executed as code, which is why this
route hands the browser ``text/plain`` and never a JavaScript MIME type: a
response the page could import would defeat the reason for the format.

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

# The largest source this route will store.
#
# A script is kilobytes. The ceiling is here because the smallest deployment
# leaves nginx's request body limit at its 1 MB default, and a limit that is
# generous on one install and default on another is the default one. Refusing at
# 256 kB gives a reason a trader can read, where letting the body grow gives them
# a gateway error with no explanation in it.
MAX_SOURCE_BYTES = 256 * 1024


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


@openscript_bp.route("/index.json", methods=["GET"])
@check_session_validity
def index():
    """List the trader's scripts, with the size and modification time of each.

    ``mtime`` is returned for the same reason the indicators route returns it:
    the page caches what it has already fetched, and an edited script would go
    on plotting its previous version until a hard refresh. ``bytes`` is returned
    so the panel can show a script it will refuse to save before the trader
    writes another line into it.
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
        scripts.append({"file": entry.name, "mtime": int(stat.st_mtime), "bytes": stat.st_size})
    return jsonify(scripts)


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
    """Create or replace one script.

    The write is atomic: the source goes to a temporary file in the same
    directory and is then moved over the target, so a process that dies partway
    leaves the previous script intact rather than a truncated one. A trader who
    has just lost a chart to a crash should not also find the script that drew
    it cut in half.

    A backup of what was there is kept beside it, which is what
    ``python_strategy`` does for the same reason: the editor is the only copy.
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

    directory = _script_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.exception("Could not create the OpenScript directory")
        return jsonify(
            {"status": "error", "message": f"Could not create the scripts folder: {error}"}
        ), 500

    target = directory / filename
    try:
        if target.exists():
            backup = target.with_name(target.name + ".bak")
            backup.write_bytes(target.read_bytes())

        # Same directory, so the move below is a rename rather than a copy
        # across filesystems, which is what makes it atomic.
        handle, temporary = tempfile.mkstemp(dir=str(directory), suffix=".partial")
        try:
            # `mkstemp` hands back a raw descriptor, and production is a single
            # worker that never restarts, so one leaked on a failure path stays
            # leaked for the life of the process. Wrapping it before the try
            # that unlinks means the wrapper owns it from here: `fdopen` either
            # takes the descriptor and closes it, or raises without taking it,
            # which is the one case the bare close below covers.
            out = os.fdopen(handle, "wb")
        except BaseException:
            os.close(handle)
            Path(temporary).unlink(missing_ok=True)
            raise

        try:
            with out:
                out.write(encoded)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
    except OSError as error:
        logger.exception("Could not save OpenScript source %s", filename)
        return jsonify({"status": "error", "message": f"Could not save: {error}"}), 500

    logger.info("Saved OpenScript source %s (%d bytes)", filename, len(encoded))
    return jsonify(
        {
            "status": "success",
            "file": filename,
            "bytes": len(encoded),
            "mtime": int(target.stat().st_mtime),
        }
    )


@openscript_bp.route("/<path:filename>", methods=["DELETE"])
@check_session_validity
def remove(filename: str):
    """Delete one script, and the backup taken of it.

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
    except OSError as error:
        logger.exception("Could not delete OpenScript source %s", filename)
        return jsonify({"status": "error", "message": f"Could not delete: {error}"}), 500

    logger.info("Deleted OpenScript source %s", filename)
    return jsonify({"status": "success", "file": filename})
