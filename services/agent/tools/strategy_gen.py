"""Write a generated Python strategy into ``strategies/scripts/``, and nothing else.

What this toolkit is for
------------------------

The agent can write an OpenAlgo strategy. Getting that script onto disk is the
one step the model cannot do for itself, so it is exposed as a tool. Reading
what is already there is the other half, because a model that cannot list the
directory invents filenames that collide or duplicates a strategy that exists.

What this toolkit deliberately does not do
------------------------------------------

**It writes a file and stops.** It never starts a strategy, never schedules
one, and never registers one for automatic start. A hosted strategy runs as a
subprocess with the operator's decrypted API key injected, which is arbitrary
code execution by design, so starting one stays a separate and explicit human
action in ``/python``. That is the build contract in
``docs/design/55-agent/README.md`` under "Generated code never runs itself", and
it is the reason this file imports nothing from ``blueprints/python_strategy.py``:
that module starts an APScheduler at import time, and a scheduled job is exactly
the automatic start this tool must not be able to cause.

Storage rules
-------------

The naming and containment rules are copied from
``blueprints/python_strategy.py:new_strategy`` so a file written here is
indistinguishable from one uploaded through ``/python``:

* ``secure_filename`` on the caller's filename,
* the stem stripped to ``[A-Za-z0-9_-]``,
* an IST ``%Y%m%d%H%M%S`` suffix, giving ``{stem}_{timestamp}.py``,
* a ``resolve()`` containment check against ``strategies/scripts/`` even though
  the name was constructed here, because a later refactor can reintroduce
  traversal and the check costs nothing.

Validation before writing
-------------------------

Three checks run before a byte is written, each raising ``RetryAgentRun`` with
the problem named so the model corrects its own output rather than the operator
discovering it at run time:

* the source parses (``ast.parse``),
* it hardcodes no credential,
* it reads ``OPENALGO_API_KEY``, ``HOST_SERVER`` and ``WEBSOCKET_URL`` from the
  environment, which is the contract in ``strategies/README.md``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from werkzeug.utils import secure_filename

from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import OpenAlgoToolkit
from utils.logging import get_logger

try:
    from agno.exceptions import RetryAgentRun
except ImportError as exc:  # pragma: no cover - exercised only without the dependency
    raise ImportError(
        "services.agent.tools.strategy_gen requires the 'agno' package. "
        "Install it with: uv add agno"
    ) from exc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")

#: Where /python reads its scripts from. Relative, exactly as
#: blueprints/python_strategy.py declares it, so both resolve to the same
#: directory. A file written anywhere else is invisible to the strategy host.
STRATEGIES_DIR = Path("strategies") / "scripts"

#: The registry /python keeps beside the scripts. Read only, and only to say
#: which files it already knows about.
CONFIG_FILE = Path("strategies") / "strategy_configs.json"

#: Upper bound on one generated script. A model that emits more than this has
#: gone wrong, and the file would be unreviewable anyway.
MAX_SOURCE_CHARS = 200_000

#: Most files described by one listing call.
MAX_LISTED_FILES = 200

#: Environment variables a hosted strategy must read, per strategies/README.md.
REQUIRED_ENV_VARS: tuple[str, ...] = ("OPENALGO_API_KEY", "HOST_SERVER", "WEBSOCKET_URL")

#: The exact snippet from strategies/README.md, handed back when a required
#: variable is missing so the correction is mechanical rather than inventive.
ENV_SNIPPET = (
    "import os\n"
    "API_KEY  = os.getenv('OPENALGO_API_KEY', '')\n"
    "API_HOST = os.getenv('HOST_SERVER') or os.getenv('OPENALGO_HOST', "
    "'http://127.0.0.1:5000')\n"
    "WS_URL   = os.getenv('WEBSOCKET_URL') or (\n"
    "    f\"ws://{os.getenv('WEBSOCKET_HOST', '127.0.0.1')}:"
    "{os.getenv('WEBSOCKET_PORT', '8765')}\"\n"
    ")"
)

#: Variable, keyword and dictionary-key names that name a credential.
_CREDENTIAL_NAME = re.compile(
    r"(api[_-]?key|apikey|api[_-]?secret|secret|password|passwd|pwd|"
    r"auth[_-]?token|access[_-]?token|refresh[_-]?token|feed[_-]?token|"
    r"client[_-]?secret|private[_-]?key|x[_-]api[_-]key|token)",
    re.IGNORECASE,
)

#: Values that name a credential slot without filling it. Assigning one of these
#: is a template, not a leak.
_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "...",
        "change_me",
        "changeme",
        "none",
        "null",
        "placeholder",
        "replace_me",
        "todo",
        "your_api_key",
        "your_key",
        "your_secret",
    }
)

#: Below this length a literal is a placeholder or a flag, not a key.
_MIN_CREDENTIAL_CHARS = 8

#: A bare literal this long, unbroken, and carrying both letters and digits is a
#: credential whatever it is assigned to. Separators are excluded deliberately:
#: an API key is one run of random characters, while a long name someone chose
#: (``supertrend_nifty_5min_strategy_v2``) is words joined by underscores, and
#: refusing to write a strategy over its own variable name would be useless.
#: URLs and paths are excluded by the character class rather than by a case.
_KEY_SHAPED_LITERAL = re.compile(r"\A[A-Za-z0-9]{32,}\Z")


def _is_placeholder(value: str) -> bool:
    """Report whether a string literal is a credential placeholder.

    Args:
        value: The literal exactly as it appears in the source.

    Returns:
        True when the value names a credential slot rather than filling it:
        empty, a known placeholder word, a ``<bracketed>`` hint, a run of
        ``x``/``*``/``.``, anything starting ``your``, all digits (an instrument
        token, not a key), or too short to be a key.
    """
    text = value.strip()
    lowered = text.lower()
    if lowered in _PLACEHOLDER_VALUES or len(text) < _MIN_CREDENTIAL_CHARS:
        return True
    if text.isdigit():
        return True
    if lowered.startswith(("your", "insert", "put_your", "enter_")):
        return True
    if text[0] in "<{[" and text[-1] in ">}]":
        return True
    return set(lowered) <= set("x*.-_ ")


def _string_constant(node: ast.AST | None) -> str | None:
    """Return the value of a string constant node.

    Args:
        node: Any AST node, or None.

    Returns:
        The string when the node is a string constant, otherwise None.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_environ(node: ast.AST) -> bool:
    """Report whether an expression node denotes ``os.environ``.

    Args:
        node: The expression being subscripted or called on.

    Returns:
        True for ``environ`` and for any ``<something>.environ``.
    """
    if isinstance(node, ast.Name):
        return node.id == "environ"
    return isinstance(node, ast.Attribute) and node.attr == "environ"


def environment_names_read(tree: ast.AST) -> set[str]:
    """Collect every environment variable the source reads by literal name.

    Recognises ``os.getenv("X")``, a bare ``getenv("X")``, ``os.environ["X"]``
    and ``os.environ.get("X")``. A lookup whose key is a variable cannot be
    resolved statically and is not counted, which is the safe direction: the
    caller is told to read the variable explicitly rather than being let
    through on a name this function could not see.

    Args:
        tree: The parsed module.

    Returns:
        The literal variable names found.
    """
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            key = _string_constant(node.slice)
            if key:
                names.add(key)
            continue

        if not isinstance(node, ast.Call) or not node.args:
            continue

        first = _string_constant(node.args[0])
        if not first:
            continue

        func = node.func
        if isinstance(func, ast.Name) and func.id == "getenv":
            names.add(first)
        elif isinstance(func, ast.Attribute):
            if func.attr == "getenv":
                names.add(first)
            elif func.attr in ("get", "setdefault") and _is_environ(func.value):
                names.add(first)

    return names


def hardcoded_credentials(tree: ast.AST) -> list[str]:
    """Find literals in the source that look like embedded credentials.

    Four shapes are checked: an assignment to a credential-named variable, a
    call keyword named like a credential, a dictionary entry whose key names
    one (the ``{"X-API-KEY": "..."}`` header pattern), and any literal long
    enough and shaped enough to be a key wherever it appears.

    The value itself is never returned. A finding names the line and the
    variable, so nothing that looks like a secret is copied into the model's
    context, a log line or an audit row.

    Args:
        tree: The parsed module.

    Returns:
        One human-readable finding per problem, empty when the source is clean.
    """
    findings: list[str] = []
    seen: set[tuple[int, str]] = set()

    def report(line: int, what: str) -> None:
        key = (line, what)
        if key not in seen:
            seen.add(key)
            findings.append(f"line {line}: {what}")

    def flag_named(line: int, name: str, value: str) -> None:
        if _CREDENTIAL_NAME.search(name) and not _is_placeholder(value):
            report(
                line,
                f"{name!r} is assigned a {len(value)}-character literal. Read it from the "
                "environment instead.",
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = _string_constant(node.value)
            if value is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        flag_named(node.lineno, target.id, value)
                    elif isinstance(target, ast.Attribute):
                        flag_named(node.lineno, target.attr, value)

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _string_constant(node.value)
            if value is not None:
                flag_named(node.lineno, node.target.id, value)

        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                value = _string_constant(keyword.value)
                if keyword.arg and value is not None:
                    flag_named(node.lineno, keyword.arg, value)

        elif isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values, strict=False):
                key = _string_constant(key_node)
                value = _string_constant(value_node)
                if key and value is not None:
                    flag_named(getattr(key_node, "lineno", node.lineno), key, value)

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if (
                _KEY_SHAPED_LITERAL.match(text)
                and any(char.isdigit() for char in text)
                and any(char.isalpha() for char in text)
            ):
                report(
                    node.lineno,
                    f"a {len(text)}-character literal is shaped like an API key or token. "
                    "Read it from the environment instead.",
                )

    return findings


class StrategyGenToolkit(OpenAlgoToolkit):
    """Save a generated Python strategy to disk, and list what is already there."""

    def __init__(self, context: ToolContext) -> None:
        """Register the two tools with agno.

        Args:
            context: The run's tool context.
        """
        super().__init__(
            context,
            name="strategy_gen",
            tools=[self.list_python_strategies, self.save_python_strategy],
            requires_confirmation_tools=["save_python_strategy"],
        )

    # -- tools ---------------------------------------------------------------

    def list_python_strategies(self) -> str:
        """List the Python strategy scripts already stored in strategies/scripts/.

        Call this before saving a new strategy, so the name you choose does not
        duplicate one that exists and so you can tell the user what they already
        have. Reading only; nothing is written and nothing is started.

        Returns:
            JSON with ``directory`` and a ``strategies`` array. Each entry has
            ``filename``, ``bytes``, ``modified`` (ISO 8601, IST),
            ``registered`` (true when the /python host already lists this file)
            and ``registered_name`` (the display name /python shows, when it has
            one). Newest first, capped at 200 entries.
        """
        directory = STRATEGIES_DIR
        entries: list[dict[str, Any]] = []

        try:
            files = [path for path in directory.glob("*.py") if path.is_file()]
        except OSError as exc:
            logger.exception("Could not list %s", directory)
            return self._result(
                "list_python_strategies",
                {
                    "ok": False,
                    "error": f"The strategies directory could not be read: {exc}",
                    "directory": str(directory),
                },
            )

        registered = self._registered_names()
        files.sort(key=lambda path: self._mtime(path), reverse=True)
        truncated = len(files) > MAX_LISTED_FILES

        for path in files[:MAX_LISTED_FILES]:
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(
                {
                    "filename": path.name,
                    "bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=IST).isoformat(),
                    "registered": path.name in registered,
                    "registered_name": registered.get(path.name),
                }
            )

        return self._result(
            "list_python_strategies",
            {
                "ok": True,
                "directory": str(directory),
                "count": len(entries),
                "total_on_disk": len(files),
                "truncated": truncated,
                "strategies": entries,
                "note": (
                    "A file with registered=false is on disk but not yet listed by the "
                    "/python strategy host. The user adds it there themselves."
                ),
            },
        )

    def save_python_strategy(self, filename: str, source: str, description: str = "") -> str:
        """Save a generated Python strategy to strategies/scripts/ without running it.

        This tool WRITES A FILE AND STOPS. It does not start the strategy, does
        not schedule it and does not register it for automatic start. Starting a
        strategy is a separate human action in the /python page, because a
        hosted strategy runs as a subprocess with the user's live API key. Tell
        the user that after saving: the file is on disk, and they start it
        themselves from /python.

        The source is refused, with the problem named so you can correct it and
        call again, when it does not parse, when it hardcodes a credential, or
        when it does not read OPENALGO_API_KEY, HOST_SERVER and WEBSOCKET_URL
        from the environment. Show the user the full source before calling this.

        Args:
            filename: Base name for the script, for example
                ``supertrend_nifty`` or ``ema_crossover.py``. The ``.py``
                extension is optional. The name is sanitised to letters, digits,
                underscore and hyphen, and a timestamp is appended, so the file
                actually written is ``ema_crossover_20260903142530.py``.
            source: The complete Python source of the strategy, exactly as it
                should land on disk. It is written verbatim, byte for byte, so
                send the same text you showed the user. It must read
                ``OPENALGO_API_KEY``, ``HOST_SERVER`` and ``WEBSOCKET_URL`` with
                ``os.getenv`` and must contain no API key, token or password.
            description: One line saying what the strategy does, for example
                ``EMA 20/50 crossover on NIFTY futures, MIS``. Recorded with the
                save and returned in the result; it is not written into the file.

        Returns:
            JSON with ``saved``, ``filename``, ``path``, ``bytes``, ``lines``,
            ``sha256`` and ``started`` (always false), plus the next step the
            user has to take in /python.
        """
        source_text = self._require_source(source)
        tree = self._require_parses(source_text)
        self._require_no_hardcoded_credentials(tree)
        self._require_environment_reads(tree)

        target = self._target_path(filename)
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

        audit_args = {
            "filename": target.name,
            "description": description,
            "source_chars": len(source_text),
            "source_sha256": digest,
        }

        with self.audited("save_python_strategy", audit_args) as audit:
            try:
                STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
                # Exclusive creation: a same-second collision on the same stem
                # must not silently replace a script the user already has.
                with open(target, "x", encoding="utf-8", newline="\n") as handle:
                    handle.write(source_text)
            except FileExistsError:
                audit.record(ok=False, response={"status": "error", "reason": "file exists"})
                return self._result(
                    "save_python_strategy",
                    {
                        "ok": False,
                        "saved": False,
                        "error": (
                            f"A file named {target.name} already exists. Call the tool again "
                            "with a slightly different filename."
                        ),
                    },
                )
            except OSError as exc:
                logger.exception("Could not write the generated strategy to %s", target)
                audit.record(ok=False, response={"status": "error", "message": str(exc)})
                return self._result(
                    "save_python_strategy",
                    {
                        "ok": False,
                        "saved": False,
                        "error": (
                            f"The strategy could not be written to {target.name}: {exc}. "
                            "This is a platform problem; report it to the user rather than "
                            "retrying."
                        ),
                    },
                )

            payload = {
                "ok": True,
                "saved": True,
                "started": False,
                "filename": target.name,
                "path": str(target),
                "directory": str(STRATEGIES_DIR),
                "bytes": len(source_text.encode("utf-8")),
                "lines": source_text.count("\n") + 1,
                "sha256": digest,
                "description": description,
                "next_step": (
                    "The file is on disk and nothing is running. The user adds it in the "
                    "/python page and starts it there. This tool never starts a strategy."
                ),
            }
            audit.record(
                ok=True,
                response={"filename": target.name, "path": str(target), "sha256": digest},
            )

        logger.info("Agent saved a generated strategy to %s", target)
        return self._result("save_python_strategy", payload)

    # -- validation ----------------------------------------------------------

    def _require_source(self, source: str) -> str:
        """Check the source is a usable non-empty string within the size cap.

        Args:
            source: The ``source`` argument as received.

        Returns:
            The source unchanged.

        Raises:
            RetryAgentRun: When it is empty, not a string, or too large.
        """
        if not isinstance(source, str):
            self.invalid_argument(
                "source",
                f"it is a {type(source).__name__}, not a string.",
                "Pass the complete Python source as one string.",
            )
        if not source.strip():
            self.invalid_argument(
                "source",
                "it is empty.",
                "Pass the complete Python source of the strategy.",
            )
        if len(source) > MAX_SOURCE_CHARS:
            self.invalid_argument(
                "source",
                f"it is {len(source)} characters, over the {MAX_SOURCE_CHARS} limit.",
                "Split the strategy up or shorten it, then call the tool again.",
            )
        return source

    def _require_parses(self, source: str) -> ast.Module:
        """Parse the source, refusing it with the syntax error located.

        Args:
            source: The strategy source.

        Returns:
            The parsed module.

        Raises:
            RetryAgentRun: When the source does not parse.
        """
        try:
            return ast.parse(source)
        except SyntaxError as exc:
            location = f"line {exc.lineno}" + (f", column {exc.offset}" if exc.offset else "")
            raise RetryAgentRun(
                f"The strategy source is not valid Python: {exc.msg} at {location}. "
                "Nothing was written. Fix the syntax error and call save_python_strategy "
                "again with the corrected source."
            ) from exc
        except ValueError as exc:
            # A null byte or a source too deeply nested for the parser.
            raise RetryAgentRun(
                f"The strategy source could not be parsed: {exc}. Nothing was written. "
                "Send plain Python text and call save_python_strategy again."
            ) from exc

    def _require_no_hardcoded_credentials(self, tree: ast.Module) -> None:
        """Refuse a source that embeds a credential.

        Args:
            tree: The parsed module.

        Raises:
            RetryAgentRun: When a credential-shaped literal is found. The
                literal itself is never included in the message.
        """
        findings = hardcoded_credentials(tree)
        if not findings:
            return
        listed = "; ".join(findings[:10])
        raise RetryAgentRun(
            "The strategy source appears to hardcode a credential, so it was not written. "
            f"{listed}. A hosted strategy reads its credentials from the environment:\n"
            f"{ENV_SNIPPET}\n"
            "Remove the literal, read the value from the environment, and call "
            "save_python_strategy again."
        )

    def _require_environment_reads(self, tree: ast.Module) -> None:
        """Refuse a source that does not read the required environment variables.

        Args:
            tree: The parsed module.

        Raises:
            RetryAgentRun: When one of :data:`REQUIRED_ENV_VARS` is not read.
        """
        found = environment_names_read(tree)
        missing = [name for name in REQUIRED_ENV_VARS if name not in found]
        if not missing:
            return
        raise RetryAgentRun(
            "The strategy source does not read "
            + ", ".join(missing)
            + " from the environment, so it was not written. A hosted OpenAlgo strategy takes "
            "its API key and its endpoints from the environment the /python host injects, "
            "never from literals, and reads them by their literal names:\n"
            f"{ENV_SNIPPET}\n"
            "Add that, use the values in the strategy, and call save_python_strategy again."
        )

    # -- paths ---------------------------------------------------------------

    def _target_path(self, filename: str) -> Path:
        """Build the path to write, applying the /python storage rules.

        The rules are copied from ``blueprints/python_strategy.py:new_strategy``:
        ``secure_filename``, the stem stripped to ``[A-Za-z0-9_-]``, an IST
        timestamp suffix, and a containment check against
        :data:`STRATEGIES_DIR` even though the name was built here.

        Args:
            filename: The caller's requested name, with or without ``.py``.

        Returns:
            The absolute-or-relative path to create.

        Raises:
            RetryAgentRun: When the name sanitises to nothing, or when the
                resolved path escapes the strategies directory.
        """
        if not isinstance(filename, str) or not filename.strip():
            self.invalid_argument(
                "filename",
                "it is empty.",
                "Pass a short name such as 'ema_crossover'.",
            )

        candidate = filename.strip()
        if not candidate.lower().endswith(".py"):
            candidate = f"{candidate}.py"

        safe_filename = secure_filename(candidate)
        if not safe_filename or not safe_filename.endswith(".py"):
            # The same check /python makes on an upload. Without it a name made
            # only of punctuation sanitises down to the extension and would be
            # saved as "py_<timestamp>.py".
            self.invalid_argument(
                "filename",
                f"{filename!r} is not a usable Python filename once sanitised.",
                "Use letters, digits, underscores or hyphens, such as 'ema_crossover'.",
            )

        safe_stem = Path(safe_filename).stem
        safe_stem = "".join(char for char in safe_stem if char.isalnum() or char in "_-")

        if not safe_stem:
            self.invalid_argument(
                "filename",
                f"{filename!r} contains no letters or digits once sanitised.",
                "Use letters, digits, underscores or hyphens, such as 'ema_crossover'.",
            )

        stamp = datetime.now(IST).strftime("%Y%m%d%H%M%S")
        target = STRATEGIES_DIR / f"{safe_stem}_{stamp}.py"

        try:
            resolved = target.resolve()
            root = STRATEGIES_DIR.resolve()
        except OSError as exc:
            logger.exception("Could not resolve the strategy path for %r", filename)
            raise RetryAgentRun(
                f"The strategy path could not be resolved: {exc}. Nothing was written."
            ) from exc

        if not resolved.is_relative_to(root):
            # Unreachable with the sanitising above, and kept because a later
            # refactor of that sanitising is exactly how traversal comes back.
            logger.warning("Rejected a generated strategy path outside %s: %s", root, resolved)
            self.invalid_argument(
                "filename",
                f"{filename!r} resolves outside the strategies directory.",
                "Use a plain name with no path separators, such as 'ema_crossover'.",
            )

        return target

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _mtime(path: Path) -> float:
        """Return a file's modification time, or 0.0 when it cannot be read.

        Args:
            path: The file to stat.

        Returns:
            Seconds since the epoch, 0.0 when the file vanished mid-listing.
        """
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _registered_names() -> dict[str, str]:
        """Map each script filename the /python host knows about to its display name.

        The registry is read, never written: it is owned by
        ``blueprints/python_strategy.py``, which holds it in memory and rewrites
        the whole file, so a write from here would be silently discarded and
        could clobber a real entry.

        Returns:
            Filename to display name. Empty when the registry is missing or
            unreadable, which is not an error: the files are still listed.
        """
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {}

        try:
            configs = json.loads(raw)
        except json.JSONDecodeError:
            # The host was rewriting it. Listing without the annotation is fine.
            return {}

        if not isinstance(configs, dict):
            return {}

        names: dict[str, str] = {}
        for strategy_id, config in configs.items():
            if not isinstance(config, dict):
                continue
            file_name = config.get("file_name")
            if not isinstance(file_name, str) or not file_name:
                file_path = config.get("file_path")
                file_name = Path(file_path).name if isinstance(file_path, str) else ""
            if file_name:
                display = config.get("name")
                names[file_name] = display if isinstance(display, str) else str(strategy_id)
        return names

    def _result(self, tool: str, payload: Any) -> str:
        """Serialise a payload and label it as data for the model.

        Args:
            tool: The tool name, written into the block's opening tag.
            payload: The result to return.

        Returns:
            A ``<tool_result>`` block wrapping the capped JSON.
        """
        return wrap_tool_result(tool, self.to_json(payload))
