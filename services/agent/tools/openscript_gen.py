"""Save an OpenScript source the agent wrote, and list the scripts already stored.

Source only, by necessity
-------------------------

The OpenScript compiler is TypeScript and runs in the browser; production
carries no JavaScript runtime and this server has no compiler (see the module
docstring of ``blueprints/openscript.py``). So the agent can store a script's
source and nothing more. That is a state the platform already has a meaning for:
a source with no compiled program beside it opens in the /trading editor, which
compiles and plots it, and nothing on the server will run it until the trader
saves it from that editor with a clean console. Every result here says so,
because "saved" must not be read as "compiled" or "deployed".

One write path
--------------

The file work is ``services.openscript_store.write_script``, the same function
the /trading save route calls: one name rule, one size limit, one per-file lock
and an atomic replace with a backup. That function removes the compiled program
of a script it replaces, so the agent asks it never to replace one that has a
program: that program is what a deployed strategy starts from, and saving source
over it would leave the next scheduled start refused. That function takes a stdlib
lock, which is green under eventlet, so the write is handed to the hub through
:func:`services.agent.tools.base.call_service` rather than made from the
agent's real thread.

Saving pauses for the operator's approval, as ``save_flow`` and
``save_python_strategy`` do: it writes a file the trader may later run.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, NoReturn
from zoneinfo import ZoneInfo

from services import openscript_store
from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import (
    SERVICE_BUSY_MESSAGE,
    OpenAlgoToolkit,
    _HubTimeout,
    call_service,
    strip_code_fence,
)
from utils import real_threading
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")

#: Most scripts described by one listing call.
MAX_LISTED_FILES = 200

#: The extension every stored script carries.
EXTENSION = ".oscript"

#: What the trader does next, stated in every successful save.
NEXT_STEP = (
    "Saved as source only. Nothing has compiled it yet, so it may still have errors, and it "
    "cannot run as a strategy until it is compiled. The trader opens /trading and picks {file} "
    "in the OpenScript editor: it compiles there, plots on the chart and lists any errors in the "
    "console. Saving it from that editor once the console is clean stores the compiled program "
    "a strategy needs before it can be backtested or deployed."
)


def _write(filename: str, source: bytes, replace: bool) -> openscript_store.SavedScript:
    """Create the folder and write one source with no program. Runs on the hub.

    Never replaces a script that has a compiled program, whatever ``replace``
    says; the store checks both under its per-file lock.

    Args:
        filename: The checked script name.
        source: The UTF-8 encoded source.
        replace: Whether an existing source of that name may be replaced.

    Returns:
        What was written.

    Raises:
        openscript_store.ScriptConflict: The name is taken and may not be replaced.
        OSError: The folder or the file could not be written.
    """
    directory = openscript_store.script_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return openscript_store.write_script(
        directory, filename, source, replace=replace, replace_compiled=False
    )


class OpenScriptToolkit(OpenAlgoToolkit):
    """Save an OpenScript source for the /trading editor, and list stored scripts."""

    def __init__(self, context: ToolContext) -> None:
        """Register the two tools with agno.

        Args:
            context: The run's tool context.
        """
        super().__init__(
            context,
            name="openscript_gen",
            tools=[self.list_openscripts, self.save_openscript],
            requires_confirmation_tools=["save_openscript"],
        )

    # -- tools ---------------------------------------------------------------

    def list_openscripts(self) -> str:
        """List the OpenScript scripts already stored in strategies/openscript/.

        Call this before saving, so a new script does not take the name of one
        the trader already has, and so you can tell them what exists. Reading
        only; nothing is written.

        Returns:
            JSON with a ``scripts`` array. Each entry has ``file``, ``bytes``,
            ``modified`` (ISO 8601, IST) and ``compiled`` (true when a compiled
            program is stored beside it, which is what a strategy needs to run).
            Sorted by name, capped at 200 entries.
        """
        tool = "list_openscripts"
        try:
            entries = openscript_store.list_scripts(openscript_store.script_dir())
        except OSError:
            logger.exception("Could not list the OpenScript folder")
            return self._result(
                tool,
                {
                    "ok": False,
                    "error": (
                        "The OpenScript folder could not be read. This is a problem on the "
                        "server; tell the operator rather than calling again."
                    ),
                },
            )

        scripts = [
            {
                "file": entry["file"],
                "bytes": entry["bytes"],
                "modified": datetime.fromtimestamp(entry["mtime"], tz=IST).isoformat(),
                "compiled": entry["program"],
            }
            for entry in entries[:MAX_LISTED_FILES]
        ]
        return self._result(
            tool,
            {
                "ok": True,
                "count": len(scripts),
                "total_on_disk": len(entries),
                "truncated": len(entries) > MAX_LISTED_FILES,
                "scripts": scripts,
                "note": (
                    "A script with compiled=false opens in the /trading OpenScript editor but "
                    "cannot run as a strategy until it is saved from there with a clean console."
                ),
            },
        )

    def save_openscript(self, filename: str, source: str, replace: bool = False) -> str:
        """Save an OpenScript study or strategy to strategies/openscript/ as source.

        Show the operator the full source before calling this. It is stored as
        source only: nothing compiles it here, so tell the operator to open it
        in the OpenScript editor on /trading, where it compiles, plots and lists
        any errors, and that saving it there with a clean console is what lets
        it run as a strategy. Never say it compiled or is running.

        A name already taken is refused unless ``replace`` is true. Call
        list_openscripts first and choose a new name. Pass replace=true only
        when the operator asked you to change that script, and tell them first
        that it will be replaced (the previous source is kept as a .bak file).
        A script that has been compiled in /trading (compiled=true in
        list_openscripts) is never replaced, even with replace=true: it may be
        deployed and running, so save under a new name or tell the operator to
        edit it in the /trading OpenScript editor.

        Args:
            filename: The script's file name, for example ``ema_cross`` or
                ``ema_cross.oscript``. The ``.oscript`` extension is added when
                missing. Letters, digits, dot, dash and underscore only,
                starting with a letter or digit, at most 64 characters before
                the extension. The name is used exactly; it is not rewritten.
            source: The complete OpenScript source, exactly as it should land
                on disk, the same text you showed the operator. At most 256 kB.
            replace: True to replace an existing script of that name that has
                no compiled program. Defaults to false, which refuses any name
                already taken.

        Returns:
            JSON with ``saved``, ``file``, ``bytes``, ``lines``, ``replaced``,
            ``compiled`` (always false) and ``next_step``, what the trader does
            in /trading.
        """
        tool = "save_openscript"
        name = self._require_filename(filename)
        text = self._require_source(source)
        encoded = text.encode("utf-8")
        allow_replace = replace is True

        audit_args = {"filename": name, "source_bytes": len(encoded), "replace": allow_replace}
        conflict: openscript_store.ScriptConflict | None = None
        with self.audited(tool, audit_args) as audit:
            try:
                saved = call_service(_write, name, encoded, allow_replace)
            except openscript_store.ScriptConflict as exc:
                reason = "compiled" if exc.compiled else "exists"
                audit.record(ok=False, response={"status": "refused", "reason": reason})
                conflict = exc
            except (real_threading.HubQueueFull, _HubTimeout):
                logger.warning("Agent OpenScript save of %s could not run in time", name)
                audit.record(ok=False, response={"status": "error", "reason": "busy"})
                return self._result(
                    tool,
                    {
                        "ok": False,
                        "saved": False,
                        "error": SERVICE_BUSY_MESSAGE.format(label="Saving the script"),
                    },
                )
            except OSError:
                logger.exception("Could not save the agent's OpenScript source %s", name)
                audit.record(ok=False, response={"status": "error", "reason": "write failed"})
                return self._result(
                    tool,
                    {
                        "ok": False,
                        "saved": False,
                        "error": (
                            f"{name} could not be written to the scripts folder. This is a "
                            "problem on the server, not with the script; tell the operator "
                            "rather than calling again."
                        ),
                    },
                )

            if conflict is None:
                payload = {
                    "ok": True,
                    "saved": True,
                    "file": saved.file,
                    "bytes": saved.bytes,
                    "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
                    "replaced": saved.replaced,
                    "backup": f"{saved.file}.bak" if saved.replaced else None,
                    "compiled": False,
                    "next_step": NEXT_STEP.format(file=saved.file),
                }
                audit.record(ok=True, response={"file": saved.file, "replaced": saved.replaced})

        if conflict is not None:
            self._refuse_taken_name(name, conflict)

        logger.info("Agent saved OpenScript source %s", saved.file)
        return self._result(tool, payload)

    # -- input handling ------------------------------------------------------

    def _require_filename(self, filename: str) -> str:
        """Check the script name against the store's rule, adding the extension.

        Args:
            filename: The ``filename`` argument as received.

        Returns:
            The name to write, ending in ``.oscript``.

        Raises:
            RetryAgentRun: When it is empty or breaks the name rule.
        """
        if not isinstance(filename, str) or not filename.strip():
            self.invalid_argument(
                "filename", "it is empty.", "Pass a short name such as 'ema_cross'."
            )
        name = filename.strip()
        if not name.lower().endswith(EXTENSION):
            name += EXTENSION
        if not openscript_store.SAFE_NAME.match(name):
            self.invalid_argument(
                "filename",
                f"{filename!r} is not a valid script name.",
                "Use letters, digits, dot, dash or underscore, starting with a letter or digit, "
                "at most 64 characters before .oscript, for example 'ema_cross'.",
            )
        return name

    def _refuse_taken_name(self, name: str, conflict: openscript_store.ScriptConflict) -> NoReturn:
        """Refuse a save whose name is already taken, saying what to do instead.

        Args:
            name: The script name the model asked for.
            conflict: What the store found under that name.

        Raises:
            RetryAgentRun: Always.
        """
        if conflict.compiled:
            self.invalid_argument(
                "filename",
                f"{name} has been compiled and saved from the /trading editor, so it may be "
                "deployed and running as a strategy, and saving source over it would stop it "
                "from starting next time. replace=true does not override this.",
                "Save under a new name, or tell the operator to make this change in the "
                "OpenScript editor on /trading.",
            )
        self.invalid_argument(
            "filename",
            f"a script named {name} already exists.",
            "Pick a new name. If the operator asked you to change that script, tell them it "
            "will be replaced (the previous version is kept as a .bak file) and call again "
            "with replace=true.",
        )

    def _require_source(self, source: str) -> str:
        """Check the source is a non-empty string within the store's size limit.

        A fence wrapped around the whole argument is removed, since that is the
        model's markdown habit rather than part of the script. Anything else is
        kept exactly.

        Args:
            source: The ``source`` argument as received.

        Returns:
            The text to write.

        Raises:
            RetryAgentRun: When it is not a string, is empty, or is too large.
        """
        if not isinstance(source, str):
            self.invalid_argument(
                "source",
                f"it is a {type(source).__name__}, not a string.",
                "Pass the complete OpenScript source as one string.",
            )
        text = strip_code_fence(source) if source.lstrip().startswith("```") else source
        if not text.strip():
            self.invalid_argument("source", "it is empty.", "Pass the complete OpenScript source.")
        size = len(text.encode("utf-8"))
        if size > openscript_store.MAX_SOURCE_BYTES:
            self.invalid_argument(
                "source",
                f"it is {size} bytes and the limit is {openscript_store.MAX_SOURCE_BYTES}.",
                "Write a shorter script.",
            )
        return text

    # -- helpers -------------------------------------------------------------

    def _result(self, tool: str, payload: Any) -> str:
        """Serialise a payload and label it as data for the model.

        Args:
            tool: The tool name, written into the block's opening tag.
            payload: The result to return.

        Returns:
            A ``<tool_result>`` block wrapping the capped JSON.
        """
        return wrap_tool_result(tool, self.to_json(payload))
