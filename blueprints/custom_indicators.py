"""
Custom Chart Indicators Blueprint.

Serves the user's own indicator modules from ``strategies/indicators`` to the
/trading chart, which imports each one at runtime and hands it the charting
library's registration API.

Why they are served rather than bundled: ``frontend/dist`` is built by CI from
what is in the repository, so anything compiled into the bundle has to be
committed first. User indicators are deliberately gitignored, which means a
bundled one would be wiped by the next ``git pull``. Loading them over HTTP at
runtime keeps them outside the build entirely, so they need no Node.js, no
rebuild, and survive an upgrade untouched.

The folder sits under ``strategies/`` because that is already the home for user
authored content and is the path Docker keeps on a named volume
(``openalgo_strategies:/app/strategies``), so indicators persist across
container rebuilds for free.
"""

import re
from pathlib import Path

from flask import Blueprint, jsonify, send_from_directory

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

custom_indicators_bp = Blueprint("custom_indicators_bp", __name__, url_prefix="/custom-indicators")

INDICATORS_DIR = Path("strategies") / "indicators"

# A served filename must match this exactly. `send_from_directory` already
# refuses to escape the directory, so this is the second layer: it keeps the
# route to plain ES modules and rejects anything with a path separator, a dot
# segment, or an extension the browser would not execute as a module.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.js$")


def _module_dir() -> Path:
    """The indicators directory, resolved against the app's working directory."""
    return INDICATORS_DIR.resolve()


@custom_indicators_bp.route("/index.json", methods=["GET"])
@check_session_validity
def index():
    """List the user's indicator modules, newest modification first.

    ``mtime`` is returned so the chart can bust the browser's module cache on
    the next load. Without it an edited indicator keeps running its previous
    version until a hard refresh, since a dynamic import of an unchanged URL is
    served from memory.
    """
    directory = _module_dir()
    if not directory.is_dir():
        return jsonify([])

    modules = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or not _SAFE_NAME.match(entry.name):
            continue
        try:
            modules.append({"file": entry.name, "mtime": int(entry.stat().st_mtime)})
        except OSError:
            # A file that vanished between listing and stat is not an error
            # worth failing the whole picker over.
            logger.exception("Could not stat custom indicator %s", entry.name)
    return jsonify(modules)


@custom_indicators_bp.route("/<path:filename>", methods=["GET"])
@check_session_validity
def module(filename: str):
    """Serve one indicator module as an ES module.

    The explicit mimetype matters: a dynamic ``import()`` refuses any response
    that is not a JavaScript MIME type, and the default guess for an unknown
    file would fail the import with an opaque error.
    """
    if not _SAFE_NAME.match(filename):
        return jsonify({"error": "Invalid indicator filename"}), 400

    directory = _module_dir()
    if not directory.is_dir():
        return jsonify({"error": "No indicators directory"}), 404

    return send_from_directory(directory, filename, mimetype="text/javascript")
