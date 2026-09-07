"""Base class every OpenAlgo agent toolkit is built on.

``OpenAlgoToolkit`` owns what every toolkit would otherwise repeat: calling the
internal service layer and turning its result into either a payload or a message
the model can act on, serialising that payload safely and within a budget, and
writing the two audit rows a mutating call owes.

Docstrings ARE the schema
-------------------------

Agno builds each tool's JSON schema from the method signature and docstring.
There is no second place to describe an argument, so a missing type hint or a
missing ``Args:`` line produces a schema the model cannot use, and it will guess.
Every tool method must look like this::

    def get_quote(self, symbol: str, exchange: str) -> str:
        \"\"\"Fetch the latest quote for one symbol.

        Args:
            symbol: OpenAlgo symbol, for example ``RELIANCE`` or
                ``NIFTY28MAR2420800CE``.
            exchange: Exchange code. One of NSE, BSE, NFO, BFO, CDS, BCD, MCX,
                NCDEX, NSE_INDEX, BSE_INDEX.

        Returns:
            JSON with the last traded price, open, high, low, close and volume.
        \"\"\"

Rules that follow from that:

* Every argument has a real type hint. ``Any`` and a bare container tell the
  model nothing; prefer ``str``, ``int``, ``float``, ``bool``, ``list[str]``.
* Every argument has a matching ``Args:`` line naming the units, the allowed
  values, and the format. The model has no other way to learn that a date is
  ``YYYY-MM-DD`` or that quantity is in shares rather than lots.
* Tools return ``str``, always through :meth:`OpenAlgoToolkit.to_json`, so a
  huge result is capped rather than blowing the context window.
* ``self`` is never part of the schema, so run state belongs on the instance
  (``self.api_key``, ``self.conversation_id``), never in an argument the model
  could set.

Writing a toolkit
-----------------

Instance attributes are assigned **before** ``super().__init__`` runs, because
agno introspects the bound methods handed to it. The base class does that for
you as long as a subclass follows the same order::

    class OrdersToolkit(OpenAlgoToolkit):
        def __init__(self, context):
            super().__init__(
                context,
                name="orders",
                tools=[self.place_order, self.cancel_order],
                requires_confirmation_tools=["place_order", "cancel_order"],
            )

Every mutating tool must be named in ``requires_confirmation_tools``. The base
class verifies each name is really one of the registered tools and refuses to
build the toolkit otherwise, because a typo there silently removes the human
approval gate instead of failing loudly.

Threading
---------

A toolkit runs on the agent's real OS thread, never on the eventlet hub. Keep
that true: call the service layer, which is safe from either world, and do not
introduce a green primitive here. See CLAUDE.md, "Nothing may block or be
blocked across the eventlet boundary".
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from datetime import date, datetime
from datetime import time as datetime_time
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TYPE_CHECKING, Any, NoReturn

from utils.logging import get_logger

try:
    from agno.exceptions import RetryAgentRun
    from agno.tools import Toolkit
except ImportError as exc:  # pragma: no cover - exercised only without the dependency
    raise ImportError(
        "services.agent.tools.base requires the 'agno' package. Install it with: uv add agno"
    ) from exc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

#: Hard ceiling on the characters a single tool may return to the model.
MAX_JSON_CHARS = 12000

#: Sequences longer than this are cut during serialisation with a trailing
#: marker. The character cap would discard the tail anyway; stopping early keeps
#: a hundred-thousand-row instrument dump from costing real CPU on the agent
#: thread before being thrown away.
MAX_SEQUENCE_ITEMS = 2000

#: Guard against a self-referencing or absurdly nested structure.
MAX_JSON_DEPTH = 16

AUDIT_PHASE_ATTEMPT = "attempt"
AUDIT_PHASE_RESULT = "result"
AUDIT_PHASE_DECISION = "decision"

#: Argument names that must never reach an audit row or a log line.
REDACTED_ARGUMENT_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "auth_token",
        "authtoken",
        "feed_token",
        "feedtoken",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "ciphertext",
    }
)

_REDACTED = "[redacted]"

#: Response keys that carry a broker order identifier, used to fill the audit
#: row's ``order_ids`` when a tool does not pass them explicitly.
_ORDER_ID_KEYS = frozenset(
    {"orderid", "order_id", "orderids", "order_ids", "trigger_id", "triggerid"}
)

#: Argument names a service error message may name. Used to tell the model
#: which of its own arguments to correct.
_KNOWN_ARGUMENT_NAMES = (
    "disclosed_quantity",
    "trigger_price",
    "instrumenttype",
    "option_type",
    "start_date",
    "underlying",
    "price_type",
    "pricetype",
    "expiry_date",
    "end_date",
    "position_size",
    "trigger_id",
    "exchange",
    "quantity",
    "strategy",
    "interval",
    "symbols",
    "orderid",
    "product",
    "symbol",
    "action",
    "expiry",
    "strike",
    "price",
    "mode",
)

_ARGUMENT_NAME_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_KNOWN_ARGUMENT_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_MISSING_FIELDS_PATTERN = re.compile(
    r"missing\s+(?:mandatory\s+|required\s+)?field\(?s?\)?\s*:?\s*(.+)", re.IGNORECASE
)

#: What the model should do about a given HTTP status. The wording matters: a
#: model told only that something failed will retry the identical call.
_STATUS_GUIDANCE: dict[int, str] = {
    400: (
        "The request was rejected as invalid. Correct the named argument and call the tool "
        "again with a valid value."
    ),
    401: (
        "Authentication was rejected. This is a configuration problem only the user can fix. "
        "Do not retry; report it."
    ),
    403: (
        "Authentication was rejected. This is a configuration problem only the user can fix. "
        "Do not retry; report it."
    ),
    404: (
        "The target was not found. Check the spelling, and resolve the exact OpenAlgo symbol "
        "and exchange with the symbol search tool before calling again."
    ),
    409: "The request conflicts with the current state. Re-read the current state before retrying.",
    422: (
        "The request was rejected as invalid. Correct the named argument and call the tool "
        "again with a valid value."
    ),
    429: (
        "Rate limited. Wait before calling again, and prefer a multi-symbol variant of the "
        "tool over many single-symbol calls."
    ),
    500: (
        "The upstream broker or service failed. Retry at most once; if it fails again, report "
        "the failure to the user instead of looping."
    ),
    501: (
        "The connected broker does not support this capability. Do not retry; tell the user "
        "their broker cannot do this."
    ),
    502: (
        "The upstream broker or service failed. Retry at most once; if it fails again, report "
        "the failure to the user instead of looping."
    ),
    503: (
        "The upstream broker or service is unavailable. Retry at most once; if it fails again, "
        "report the failure to the user instead of looping."
    ),
    504: (
        "The upstream broker or service timed out. Retry at most once; if it fails again, "
        "report the failure to the user instead of looping."
    ),
}

_DEFAULT_GUIDANCE = (
    "Correct the arguments and call the tool again, or report the failure to the user if it "
    "cannot be corrected."
)

_TRUNCATION_NOTE = (
    "The result was too large to return in full. 'partial' holds the beginning of the JSON and "
    "may stop mid-value. Narrow the request (fewer symbols, a shorter date range, a filter) and "
    "call the tool again."
)

# Set once when the audit sink is absent, so a build without database/agent_db.py
# logs the fact a single time instead of on every mutating call.
_audit_sink_warned = False


# ---------------------------------------------------------------------------
# JSON safety
# ---------------------------------------------------------------------------


def _finite_or_none(value: float) -> float | None:
    """Return the value, or None when it is NaN or an infinity.

    Args:
        value: Any float.

    Returns:
        The value when finite, otherwise None so it serialises as JSON ``null``.
    """
    return value if math.isfinite(value) else None


def as_number(value: Any) -> float | None:
    """Coerce a field a service returned into a finite float.

    The one numeric coercion the tool layer has. A broker sends a price as a
    float, as an integer, as a numeric string or as a numpy scalar depending on
    the plugin, and every toolkit that does arithmetic on one needs the same
    answer for all four. Keeping it here rather than in each toolkit is what
    stops a second copy drifting: the copy that goes wrong is always the one in
    the path nobody is looking at.

    Args:
        value: The raw field.

    Returns:
        The value as a float, or None when it is missing, is a boolean, is not a
        number at all, or is a NaN or an infinity. None is what both Plotly and
        ``openalgo-charts`` read as a gap, and it is the honest rendering of a
        figure the exchange did not supply.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    return number if math.isfinite(number) else None


def format_number(value: Any) -> str:
    """Format a number for the one-line confirmation a tool returns to the model.

    Args:
        value: The number, or anything else.

    Returns:
        A short plain rendering. Large values keep no decimals and smaller ones
        keep at most two, so a confirmation stays a sentence rather than a wall
        of digits. A value that is not a number reads as ``unknown``, which is
        what it is.
    """
    number = as_number(value)
    if number is None:
        return "unknown"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def format_price(value: Any) -> str:
    """Format a traded price or a rupee figure for a confirmation line.

    Separate from :func:`format_number` because the two are formatting different
    things. A count of open interest contracts is read at a glance and its last
    two digits are noise, so it is rounded; a price is a price, and the paise
    are part of it. ``1,302`` is not what the instrument traded at and
    ``1,302.50`` is, which matters when the model repeats the figure to the
    operator.

    Args:
        value: The price, or anything else.

    Returns:
        The value with thousands separators and two decimals, or ``unknown``
        when it is not a number.
    """
    number = as_number(value)
    if number is None:
        return "unknown"
    return f"{number:,.2f}"


def json_safe(value: Any, _depth: int = 0, _path: frozenset[int] | None = None) -> Any:
    """Convert an arbitrary Python object into something ``json.dumps`` accepts.

    NaN and the infinities become ``null`` rather than the ``NaN`` literal that
    ``json.dumps`` emits by default, because that literal is not valid JSON and
    a model will read it as a name. Decimals, datetimes, enums, dataclasses,
    pydantic models, namedtuples and numpy or pandas containers are converted to
    their natural JSON shape. Anything else falls back to ``str``; instance
    dictionaries are deliberately not walked, so an object holding a broker
    client or a credential cannot leak its internals into a tool result.

    Args:
        value: The object to convert.
        _depth: Current recursion depth. Internal.
        _path: Ids of the containers on the current path, for cycle detection.
            Internal.

    Returns:
        A structure built only from dict, list, str, int, float, bool and None.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value

    if isinstance(value, float):
        return _finite_or_none(value)

    if isinstance(value, Decimal):
        try:
            return _finite_or_none(float(value))
        except (ValueError, OverflowError, InvalidOperation):
            return str(value)

    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()

    if isinstance(value, Enum):
        return json_safe(value.value, _depth + 1, _path)

    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")

    if _depth >= MAX_JSON_DEPTH:
        return f"<max depth {MAX_JSON_DEPTH} exceeded: {type(value).__name__}>"

    path = _path or frozenset()
    marker = id(value)
    if marker in path:
        return "<circular reference>"
    path = path | {marker}

    if isinstance(value, Mapping):
        return {
            (key if isinstance(key, str) else str(key)): json_safe(item, _depth + 1, path)
            for key, item in value.items()
        }

    # pandas DataFrame and anything else that describes itself as rows.
    if hasattr(value, "columns") and hasattr(value, "to_dict"):
        try:
            return json_safe(value.to_dict(orient="records"), _depth + 1, path)
        except (TypeError, ValueError):
            logger.exception("Could not convert a tabular value of type %s", type(value).__name__)
            return str(value)

    # numpy arrays and pandas Series.
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        try:
            return json_safe(value.tolist(), _depth + 1, path)
        except (TypeError, ValueError):
            logger.exception("Could not convert an array value of type %s", type(value).__name__)
            return str(value)

    # numpy scalars.
    if hasattr(value, "item") and not isinstance(value, (Sequence, Mapping)):
        try:
            return json_safe(value.item(), _depth + 1, path)
        except (TypeError, ValueError):
            return str(value)

    if hasattr(value, "model_dump"):
        try:
            return json_safe(value.model_dump(), _depth + 1, path)
        except (TypeError, ValueError):
            logger.exception("Could not dump a model of type %s", type(value).__name__)
            return str(value)

    if hasattr(value, "_asdict"):
        try:
            return json_safe(value._asdict(), _depth + 1, path)
        except (TypeError, ValueError):
            return str(value)

    if is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: json_safe(getattr(value, f.name, None), _depth + 1, path)
            for f in dataclass_fields(value)
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if len(items) > MAX_SEQUENCE_ITEMS:
            kept = [json_safe(item, _depth + 1, path) for item in items[:MAX_SEQUENCE_ITEMS]]
            kept.append(f"... {len(items) - MAX_SEQUENCE_ITEMS} more items omitted")
            return kept
        return [json_safe(item, _depth + 1, path) for item in items]

    return str(value)


def _dumps(payload: Any) -> str:
    """Serialise an already-sanitised payload to compact JSON.

    Args:
        payload: The output of :func:`json_safe`.

    Returns:
        A JSON string. ``allow_nan`` is off so a non-finite value that slipped
        through raises here instead of producing invalid JSON.
    """
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        logger.exception("Falling back to str() serialisation for an agent tool result")

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
    except (TypeError, ValueError):
        logger.exception("An agent tool result could not be serialised as JSON at all")
        return json.dumps(
            {
                "ok": False,
                "error": "The result could not be serialised as JSON.",
                "repr": str(payload)[:2000],
            },
            ensure_ascii=False,
        )


def _truncation_envelope(partial: str, dropped_chars: int) -> str:
    """Build the well-formed object returned in place of an oversized result.

    Args:
        partial: Leading characters of the full JSON text.
        dropped_chars: How many characters of that text were dropped.

    Returns:
        A JSON object string carrying the partial text as a proper JSON string,
        so the model receives valid JSON rather than a payload cut mid-value.
    """
    return json.dumps(
        {
            "ok": True,
            "truncated": True,
            "dropped_chars": dropped_chars,
            "partial": partial,
            "note": _TRUNCATION_NOTE,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def dumps_capped(obj: Any, limit: int = MAX_JSON_CHARS) -> str:
    """Serialise any object to JSON no longer than ``limit`` characters.

    Args:
        obj: The object to serialise.
        limit: Maximum characters in the returned string.

    Returns:
        Compact JSON, or a truncation envelope of the form
        ``{"ok": true, "truncated": true, "dropped_chars": N, "partial": "..."}``
        when the full text would not fit.
    """
    text = _dumps(json_safe(obj))
    if len(text) <= limit:
        return text

    # Binary search the longest prefix whose envelope still fits. The envelope
    # length moves with both the prefix and the digit count of dropped_chars, so
    # each candidate is measured rather than estimated.
    low, high = 0, len(text)
    best = _truncation_envelope("", len(text))
    while low <= high:
        middle = (low + high) // 2
        candidate = _truncation_envelope(text[:middle], len(text) - middle)
        if len(candidate) <= limit:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def redact_arguments(args: Any) -> Any:
    """Replace credential-bearing values in a mapping of tool arguments.

    Args:
        args: Mapping of argument names to values, or any other structure.

    Returns:
        The same structure with every value whose key looks like a credential
        replaced by a fixed marker. Nested mappings are covered too.
    """
    if isinstance(args, Mapping):
        return {
            str(key): (
                _REDACTED
                if str(key).strip().lower() in REDACTED_ARGUMENT_NAMES
                else redact_arguments(value)
            )
            for key, value in args.items()
        }
    if isinstance(args, (list, tuple)):
        return [redact_arguments(item) for item in args]
    return args


def invalid_argument(field: str, reason: str, fix: str | None = None) -> NoReturn:
    """Reject a tool argument with a message the model can act on.

    Module level rather than a method so a helper lifted out of a toolkit can
    still refuse an argument the same way the toolkit does.
    :meth:`OpenAlgoToolkit.invalid_argument` delegates here, so there is exactly
    one wording of a rejection.

    Args:
        field: Name of the offending argument, exactly as the model sees it.
        reason: Why the value is unusable.
        fix: What a valid value looks like.

    Raises:
        RetryAgentRun: Always.
    """
    message = f"The '{field}' argument is invalid: {reason}"
    if fix:
        message += f" {fix}"
    raise RetryAgentRun(message)


def strip_code_fence(text: str) -> str:
    """Remove a Markdown code fence wrapped around a tool argument.

    Every tool that takes a whole document as a string meets the same slip: the
    model has spent the turn writing markdown and fences the argument out of
    habit. Unwrapping it is cheaper than spending a turn on a parse error that
    says nothing about the document itself.

    Module level, and shared, because the alternative is a copy in every such
    tool. Two copies of this drift, and the copy that goes wrong is the one in
    the path nobody is looking at.

    Args:
        text: The raw argument.

    Returns:
        The text with a leading fence line and a trailing fence removed,
        unchanged when there is no fence.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


# ---------------------------------------------------------------------------
# Audit scope
# ---------------------------------------------------------------------------


class AuditScope:
    """Carrier for the outcome of one mutating tool call.

    Created by :meth:`OpenAlgoToolkit.audited`. The tool body calls
    :meth:`record` exactly once with the outcome; the context manager writes the
    single ``result`` row when the block ends, whether it ended normally or by
    raising.

    Attributes:
        tool: Tool name being audited.
        args: Redacted arguments recorded with the attempt.
        risk_verdict: Verdict string from the risk guard, when one ran.
        attempt_id: Row id of the ``attempt`` row, when the sink returned one.
        ok: Outcome recorded by the tool body.
        response: Response payload recorded by the tool body.
        order_ids: Broker order ids recorded by the tool body.
        recorded: True once :meth:`record` has been called.
    """

    __slots__ = (
        "args",
        "attempt_id",
        "ok",
        "order_ids",
        "recorded",
        "response",
        "risk_verdict",
        "tool",
    )

    def __init__(self, tool: str, args: Any, risk_verdict: str | None) -> None:
        """Initialise an empty scope.

        Args:
            tool: Tool name being audited.
            args: Already-redacted arguments.
            risk_verdict: Verdict from the risk guard, when one ran.
        """
        self.tool = tool
        self.args = args
        self.risk_verdict = risk_verdict
        self.attempt_id: int | None = None
        self.ok: bool = False
        self.response: Any = None
        self.order_ids: list[str] | None = None
        self.recorded = False

    def record(
        self, ok: bool, response: Any = None, order_ids: Sequence[str] | None = None
    ) -> None:
        """Record the outcome of the call.

        Args:
            ok: True when the mutation succeeded.
            response: Service response payload, stored on the audit row.
            order_ids: Broker order ids. Derived from ``response`` when omitted.
        """
        self.ok = bool(ok)
        self.response = response
        self.order_ids = list(order_ids) if order_ids is not None else None
        self.recorded = True


# ---------------------------------------------------------------------------
# The toolkit base
# ---------------------------------------------------------------------------


class OpenAlgoToolkit(Toolkit):
    """Base class for every agent toolkit.

    Subclasses assign nothing before calling ``super().__init__``; this class
    sets the run attributes first and only then hands the bound methods to agno,
    which introspects them immediately.

    Attributes:
        context: The run's tool context.
        api_key: OpenAlgo API key for the run, passed to the service layer.
        conversation_id: Conversation the run belongs to, recorded on audit rows.
        run_id: Agno run id for the current turn, when known.
        session_id: Agno session id for the current turn, when known.
        surface: ``chat`` or ``chart``.
        trading_enabled: Whether the session may place orders.
        analyzer_mode: Whether the platform analyzer toggle is on.
        session_state: The session-state mapping the context came from.
        declared_tools: Names of the tools handed to agno.
    """

    #: When true, :meth:`service_call` fills in ``api_key`` for any service
    #: function that declares the parameter and was not given one. Set it to
    #: False on a subclass that calls services with its own credentials.
    inject_api_key: bool = True

    def __init__(
        self,
        context: ToolContext,
        *,
        name: str | None = None,
        tools: Sequence[Callable[..., Any]] | None = None,
        requires_confirmation_tools: Sequence[str | Callable[..., Any]] | None = None,
        instructions: str | None = None,
        add_instructions: bool = False,
        **kwargs: Any,
    ) -> None:
        """Store the run context, then register the tools with agno.

        Args:
            context: The run's tool context. Must carry ``api_key``.
            name: Toolkit name. Defaults to the snake-case class name with a
                trailing ``Toolkit`` removed.
            tools: Bound methods to expose as tools, in the order the model
                should see them.
            requires_confirmation_tools: Names, or the bound methods themselves,
                of the tools that pause the run for human approval. Every
                mutating tool belongs here.
            instructions: Extra instructions agno appends to the system message.
            add_instructions: Whether agno should add those instructions.
            **kwargs: Passed through to agno's ``Toolkit``. Keys the installed
                agno does not accept are dropped with a debug log.

        Raises:
            ValueError: If the context carries no API key, or a confirmation
                name does not match a registered tool.
            RuntimeError: If confirmations were requested and the installed agno
                cannot enforce them.
        """
        # Assigned before super().__init__ because agno introspects the bound
        # methods in `tools` as soon as it receives them.
        self.context = context
        self.api_key: str = getattr(context, "api_key", "") or ""
        self.conversation_id = getattr(context, "conversation_id", None)
        self.run_id = getattr(context, "run_id", None)
        self.session_id = getattr(context, "session_id", None)
        self.user_id = getattr(context, "user_id", None)
        self.surface: str = getattr(context, "surface", "chat") or "chat"
        self.trading_enabled: bool = bool(getattr(context, "trading_enabled", False))
        self.analyzer_mode: bool = bool(getattr(context, "analyzer_mode", False))
        state = getattr(context, "session_state", None)
        self.session_state: dict[str, Any] = dict(state) if isinstance(state, Mapping) else {}

        if not self.api_key:
            raise ValueError(
                f"{type(self).__name__} was built with a context carrying no OpenAlgo api_key"
            )

        tool_list = list(tools or [])
        self.declared_tools: list[str] = [self._tool_name(tool) for tool in tool_list]
        confirmations = self._normalise_confirmations(requires_confirmation_tools)

        super_kwargs: dict[str, Any] = {
            "name": name or self.default_name(),
            "tools": tool_list,
            "instructions": instructions,
            "add_instructions": add_instructions,
            **kwargs,
        }
        if confirmations:
            super_kwargs["requires_confirmation_tools"] = confirmations

        super().__init__(**self._filter_super_kwargs(super_kwargs))

    # -- construction helpers ------------------------------------------------

    @classmethod
    def default_name(cls) -> str:
        """Derive the toolkit name from the class name.

        Returns:
            The snake-case class name with a trailing ``Toolkit`` removed, for
            example ``market`` for ``MarketToolkit``.
        """
        name = cls.__name__
        if name.endswith("Toolkit") and len(name) > len("Toolkit"):
            name = name[: -len("Toolkit")]
        out: list[str] = []
        for index, char in enumerate(name):
            if char.isupper() and index and not name[index - 1].isupper():
                out.append("_")
            out.append(char.lower())
        return "".join(out)

    @staticmethod
    def _tool_name(tool: Any) -> str:
        """Return the name agno will register a tool under.

        Args:
            tool: A bound method, a plain function, or an agno ``Function``.

        Returns:
            The tool's name, or its repr when it has none.
        """
        return getattr(tool, "__name__", None) or getattr(tool, "name", None) or repr(tool)

    def _normalise_confirmations(
        self, requested: Sequence[str | Callable[..., Any]] | None
    ) -> list[str]:
        """Turn the confirmation list into names and check every one is real.

        A name that matches no registered tool is a typo, and a typo here would
        quietly remove the human approval gate from a mutating tool. It is
        refused at construction instead.

        Args:
            requested: Names or bound methods that require confirmation.

        Returns:
            The tool names requiring confirmation, de-duplicated in order.

        Raises:
            ValueError: If a requested name is not one of the declared tools.
        """
        if not requested:
            return []

        declared = set(self.declared_tools)
        names: list[str] = []
        for item in requested:
            name = item if isinstance(item, str) else self._tool_name(item)
            if name not in declared:
                raise ValueError(
                    f"{type(self).__name__} requires confirmation for {name!r}, which is not one "
                    f"of its registered tools ({', '.join(sorted(declared)) or 'none'}). "
                    "A mutating tool that is not registered would run without approval."
                )
            if name not in names:
                names.append(name)
        return names

    def _filter_super_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Drop keyword arguments the installed agno ``Toolkit`` does not accept.

        Agno's ``Toolkit`` signature has changed across releases. Dropping an
        unknown cosmetic keyword is better than failing to build the toolkit,
        but dropping the confirmation list would remove a safety gate, so that
        one is an error instead.

        Args:
            kwargs: The keyword arguments intended for ``Toolkit.__init__``.

        Returns:
            The subset the installed agno accepts.

        Raises:
            RuntimeError: If confirmations were requested and cannot be passed.
        """
        try:
            parameters = inspect.signature(Toolkit.__init__).parameters
        except (TypeError, ValueError):
            return kwargs

        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
            return kwargs

        accepted = {name for name in parameters if name != "self"}
        dropped = sorted(key for key in kwargs if key not in accepted)
        if not dropped:
            return kwargs

        if "requires_confirmation_tools" in dropped and kwargs.get("requires_confirmation_tools"):
            raise RuntimeError(
                "The installed agno Toolkit does not accept requires_confirmation_tools, so "
                f"{type(self).__name__} cannot enforce human approval on its mutating tools. "
                "Upgrade agno rather than running without the approval gate."
            )

        logger.debug(
            "Toolkit %s: dropping keyword(s) the installed agno does not accept: %s",
            type(self).__name__,
            ", ".join(dropped),
        )
        return {key: value for key, value in kwargs.items() if key in accepted}

    # -- service layer -------------------------------------------------------

    def service_call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call an internal service function and return its payload.

        This is how a tool reaches OpenAlgo. It never makes an HTTP request back
        into this process; ``fn`` is imported from ``services.*`` and called
        directly. The service layer's ``(success, response, status_code)`` tuple
        is unwrapped here, and the shapes that do not follow that contract
        (``get_instruments`` returns four items, alert and bot methods return
        booleans, several internals return a plain dict) are detected rather
        than assumed.

        When :attr:`inject_api_key` is true and ``fn`` declares an ``api_key``
        parameter that the caller did not supply, the run's key is filled in, so
        no tool has to remember it.

        Args:
            fn: The service function, imported from ``services.*``.
            *args: Positional arguments for ``fn``.
            **kwargs: Keyword arguments for ``fn``.

        Returns:
            The service payload on success. For the standard tuple that is the
            response dictionary; for a service returning a plain value it is
            that value.

        Raises:
            RetryAgentRun: On any failure, carrying a message that names the
                argument to fix and says whether retrying is worthwhile.
        """
        label = self._describe(fn)
        call_kwargs = self._with_api_key(fn, args, kwargs)

        try:
            result = fn(*args, **call_kwargs)
        except RetryAgentRun:
            raise
        except Exception as exc:
            logger.exception("Agent toolkit %s: %s raised", type(self).__name__, label)
            raise RetryAgentRun(
                f"{label} raised {type(exc).__name__}: {exc}. "
                "Check the arguments you passed; if they are correct, this is a platform failure "
                "and you should report it to the user rather than calling the tool again."
            ) from exc

        return self.unwrap_service_result(result, label=label)

    def unwrap_service_result(self, result: Any, label: str = "the service call") -> Any:
        """Unwrap a service result that was obtained without :meth:`service_call`.

        Args:
            result: Whatever the service function returned.
            label: Human-readable name of the call, used in the failure message.

        Returns:
            The payload on success.

        Raises:
            RetryAgentRun: When the result reports failure.
        """
        success, payload, status = self._split_service_result(result)
        if success:
            return payload
        raise RetryAgentRun(self._failure_message(label, payload, status))

    def _with_api_key(
        self, fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """Return ``kwargs`` with the run's API key added when it belongs there.

        Args:
            fn: The service function about to be called.
            args: Positional arguments the caller supplied.
            kwargs: Keyword arguments the caller supplied.

        Returns:
            The keyword arguments to use. Unchanged when the function takes no
            ``api_key``, when one was already supplied positionally or by
            keyword, or when injection is switched off on the toolkit.
        """
        if not self.inject_api_key or "api_key" in kwargs:
            return dict(kwargs)

        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return dict(kwargs)

        if "api_key" not in signature.parameters:
            return dict(kwargs)

        try:
            bound = signature.bind_partial(*args, **kwargs)
        except TypeError:
            # Let the real call raise the argument error rather than masking it.
            return dict(kwargs)

        if "api_key" in bound.arguments:
            return dict(kwargs)

        merged = dict(kwargs)
        merged["api_key"] = self.api_key
        return merged

    @staticmethod
    def _describe(fn: Callable[..., Any]) -> str:
        """Build a short readable name for a service function.

        Args:
            fn: The service function, possibly a ``functools.partial``.

        Returns:
            Something like ``quotes_service.get_quotes``.
        """
        name = getattr(fn, "__name__", None)
        module = getattr(fn, "__module__", None)
        if not name:
            inner = getattr(fn, "func", None)
            if inner is not None:
                name = getattr(inner, "__name__", None)
                module = getattr(inner, "__module__", module)
        if not name:
            return repr(fn)
        if module:
            return f"{module.rsplit('.', 1)[-1]}.{name}"
        return name

    @staticmethod
    def _split_service_result(result: Any) -> tuple[bool, Any, int | None]:
        """Detect the shape of a service result and split it.

        Handles, in order: the standard ``(success, response, status_code)``
        tuple; the four-item ``(success, payload, status_code, headers)`` shape
        that ``get_instruments`` uses for CSV downloads; the internal validator
        shape ``(success, payload, error_message)`` whose third item is a string
        rather than a status; a two-item ``(success, payload)``; a bare boolean
        from an alert or bot method; and a plain dictionary carrying
        ``status`` or ``success``. Anything else is taken at face value as a
        successful payload, which is what scheduler, cache and analytics
        services return.

        Args:
            result: The value the service function returned.

        Returns:
            A ``(success, payload, status_code)`` triple. ``status_code`` is
            None when the shape did not carry one.
        """
        if isinstance(result, tuple):
            items = list(result)
            first = items[0] if items else None

            if len(items) in (3, 4) and isinstance(first, bool):
                third = items[2]
                if isinstance(third, bool):
                    pass
                elif isinstance(third, int):
                    return first, items[1], third
                elif third is None:
                    return first, items[1], None
                elif isinstance(third, str):
                    # (success, payload, error_message) from an internal validator.
                    payload = items[1] if first else {"status": "error", "message": third}
                    return first, payload, None

            if len(items) == 2 and isinstance(first, bool):
                return first, items[1], None

        if isinstance(result, bool):
            return result, {"status": "success" if result else "error"}, None

        if isinstance(result, Mapping):
            status_field = result.get("status")
            success_field = result.get("success")
            if isinstance(status_field, str) and status_field.strip().lower() == "error":
                return False, result, _as_status_code(result.get("code"))
            if success_field is False:
                return False, result, _as_status_code(result.get("code"))
            return True, result, None

        return True, result, None

    def _failure_message(self, label: str, payload: Any, status: int | None) -> str:
        """Compose a failure message the model can act on.

        Args:
            label: Name of the call that failed.
            payload: The error payload the service returned.
            status: HTTP status code, when the service supplied one.

        Returns:
            A message naming the call, the reason, the arguments that look
            wrong, and what the model should do next.
        """
        detail = _extract_detail(payload)
        parts = [f"{label} failed" + (f" (HTTP {status})" if status else "")]
        parts[0] += f": {detail}" if detail else "."

        fields = _guess_fields(detail)
        if fields:
            named = ", ".join(f"'{name}'" for name in fields)
            parts.append(f"The problem is with the argument(s) {named}.")

        parts.append(_STATUS_GUIDANCE.get(status or 0, _DEFAULT_GUIDANCE))
        return " ".join(parts)

    def invalid_argument(self, field: str, reason: str, fix: str | None = None) -> NoReturn:
        """Reject an argument from inside a tool body with an actionable message.

        Use this for a check the tool makes itself, before any service is
        called, so the model gets the same shape of feedback it would get from a
        service rejection. A thin delegate to the module-level
        :func:`invalid_argument`, which is the single wording of a rejection.

        Args:
            field: Name of the offending argument, exactly as the model sees it.
            reason: Why the value is unusable.
            fix: What a valid value looks like.

        Raises:
            RetryAgentRun: Always.
        """
        invalid_argument(field, reason, fix)

    # -- serialisation -------------------------------------------------------

    def to_json(self, obj: Any) -> str:
        """Serialise a tool result to JSON the model can read.

        NaN and the infinities become ``null``, Decimals and datetimes are
        converted, and the whole string is capped at
        :data:`MAX_JSON_CHARS` characters. An oversized result comes back as a
        well-formed object rather than JSON cut off mid-value::

            {"ok": true, "truncated": true, "dropped_chars": 41230, "partial": "..."}

        A tool that knows its result is a list should slice it before calling
        this, because dropping rows deliberately reads far better to the model
        than dropping characters.

        Args:
            obj: The result to serialise. Any Python object.

        Returns:
            A JSON string of at most :data:`MAX_JSON_CHARS` characters.
        """
        return dumps_capped(obj, MAX_JSON_CHARS)

    # -- audit ---------------------------------------------------------------

    def audit_attempt(
        self, tool: str, args: Mapping[str, Any] | None = None, risk_verdict: str | None = None
    ) -> int | None:
        """Record the intent to perform a mutating call, before it is dispatched.

        Args:
            tool: Name of the tool being run.
            args: The arguments it will use. Credential-bearing keys are
                redacted before the row is written.
            risk_verdict: Verdict from the risk guard, when one has already run.

        Returns:
            The audit row id when the sink returned one, otherwise None.
        """
        return self._write_audit(
            AUDIT_PHASE_ATTEMPT,
            tool=tool,
            args=redact_arguments(args) if args is not None else None,
            risk_verdict=risk_verdict,
        )

    def audit_result(
        self,
        tool: str,
        ok: bool,
        response: Any = None,
        order_ids: Sequence[str] | None = None,
        attempt_id: int | None = None,
        risk_verdict: str | None = None,
    ) -> int | None:
        """Record the outcome of a mutating call.

        Args:
            tool: Name of the tool that ran.
            ok: True when the mutation succeeded.
            response: Service response payload.
            order_ids: Broker order ids. Extracted from ``response`` when not
                given, so a caller cannot forget them.
            attempt_id: Row id of the matching ``attempt`` row, when known.
            risk_verdict: Verdict from the risk guard, when one ran.

        Returns:
            The audit row id when the sink returned one, otherwise None.
        """
        ids = list(order_ids) if order_ids is not None else self.extract_order_ids(response)
        return self._write_audit(
            AUDIT_PHASE_RESULT,
            tool=tool,
            ok=bool(ok),
            response=response,
            order_ids=ids,
            attempt_id=attempt_id,
            risk_verdict=risk_verdict,
        )

    def audit_decision(
        self,
        tool: str,
        approved: bool,
        args: Mapping[str, Any] | None = None,
        risk_verdict: str | None = None,
    ) -> int | None:
        """Record a human approval decision on a paused mutating call.

        Args:
            tool: Name of the tool awaiting approval.
            approved: True when the user approved the call.
            args: The arguments shown to the user, redacted before writing.
            risk_verdict: Verdict from the risk guard, when one ran.

        Returns:
            The audit row id when the sink returned one, otherwise None.
        """
        return self._write_audit(
            AUDIT_PHASE_DECISION,
            tool=tool,
            ok=bool(approved),
            args=redact_arguments(args) if args is not None else None,
            risk_verdict=risk_verdict,
        )

    @contextmanager
    def audited(
        self,
        tool: str,
        args: Mapping[str, Any] | None = None,
        risk_verdict: str | None = None,
    ) -> Iterator[AuditScope]:
        """Wrap a mutating call in the attempt/result audit pair.

        The ``attempt`` row is written before the block runs and the ``result``
        row when it ends, including when the block raises, so a call that blew
        up between dispatch and response is still visible. The tool body must
        call :meth:`AuditScope.record` with the outcome::

            with self.audited("place_order", args) as audit:
                response = self.service_call(place_order, order_data)
                audit.record(ok=True, response=response)

        Args:
            tool: Name of the tool being run.
            args: Arguments for the attempt row, redacted before writing.
            risk_verdict: Verdict from the risk guard, when one has already run.

        Yields:
            The :class:`AuditScope` to record the outcome on.
        """
        safe_args = redact_arguments(args) if args is not None else None
        scope = AuditScope(tool=tool, args=safe_args, risk_verdict=risk_verdict)
        scope.attempt_id = self.audit_attempt(tool, args, risk_verdict)

        try:
            yield scope
        except BaseException as exc:
            response: dict[str, Any] = {}
            if isinstance(scope.response, Mapping):
                response.update(scope.response)
            elif scope.recorded and scope.response is not None:
                response["result"] = scope.response
            response["exception"] = f"{type(exc).__name__}: {exc}"
            self.audit_result(
                tool,
                ok=scope.ok if scope.recorded else False,
                response=response,
                order_ids=scope.order_ids,
                attempt_id=scope.attempt_id,
                risk_verdict=risk_verdict,
            )
            raise

        if scope.recorded:
            self.audit_result(
                tool,
                ok=scope.ok,
                response=scope.response,
                order_ids=scope.order_ids,
                attempt_id=scope.attempt_id,
                risk_verdict=risk_verdict,
            )
        else:
            # A mutating tool that records nothing is a coding error. Say so on
            # the row rather than claiming an outcome nobody reported.
            self.audit_result(
                tool,
                ok=False,
                response={
                    "status": "unknown",
                    "message": "The tool returned without recording an audit outcome.",
                },
                attempt_id=scope.attempt_id,
                risk_verdict=risk_verdict,
            )

    @staticmethod
    def extract_order_ids(response: Any) -> list[str]:
        """Pull every broker order id out of a service response.

        Walks the response looking for the keys OpenAlgo services use for an
        order identifier, including the nested ``results`` lists that the basket,
        split and multi-leg services return.

        Args:
            response: A service response payload, or None.

        Returns:
            The order ids found, de-duplicated, in the order encountered.
        """
        found: list[str] = []
        seen: set[str] = set()

        def walk(node: Any, depth: int) -> None:
            if depth > MAX_JSON_DEPTH or len(found) >= 200:
                return
            if isinstance(node, Mapping):
                for key, value in node.items():
                    if str(key).strip().lower() in _ORDER_ID_KEYS:
                        for item in value if isinstance(value, (list, tuple)) else [value]:
                            if item is None or isinstance(item, (Mapping, list, tuple)):
                                continue
                            text = str(item).strip()
                            if text and text not in seen:
                                seen.add(text)
                                found.append(text)
                    else:
                        walk(value, depth + 1)
            elif isinstance(node, (list, tuple)):
                for item in node:
                    walk(item, depth + 1)

        walk(response, 0)
        return found

    def _write_audit(self, phase: str, **row: Any) -> int | None:
        """Write one audit row, swallowing every failure.

        The audit trail must never stop a trade, so a missing sink or a database
        error is logged and the call continues. The sink lives in
        ``database.agent_db`` and is imported here rather than at module import
        so this module stays usable before that table exists.

        The sink is ``database.agent_db.record_audit``::

            record_audit(phase, tool, conversation_id=None, run_id=None,
                         args=None, risk_verdict=None, ok=None,
                         response=None, order_ids=None) -> int | None

        A sink that does not model every column this class passes is still used;
        the extra keywords are dropped once, with a warning naming them, because
        losing one field is better than losing every row to a ``TypeError``.
        ``attempt_id`` is the one the current sink does not carry: the pair is
        tied together by ``run_id`` and ``tool`` instead.

        Args:
            phase: ``attempt``, ``result`` or ``decision``.
            **row: The remaining audit columns.

        Returns:
            The row id the sink returned, or None when nothing was written.
        """
        global _audit_sink_warned

        try:
            from database.agent_db import record_audit
        except ImportError:
            if not _audit_sink_warned:
                _audit_sink_warned = True
                logger.warning(
                    "database.agent_db.record_audit is unavailable; agent tool calls will "
                    "not be audited"
                )
            return None

        row["phase"] = phase
        row["conversation_id"] = self.conversation_id
        row["run_id"] = self.run_id

        try:
            return record_audit(**_audit_sink_kwargs(record_audit, row))
        except Exception:
            logger.exception(
                "Failed to write the %s audit row for agent tool %r", phase, row.get("tool")
            )
            return None


# ---------------------------------------------------------------------------
# Audit sink adaptation
# ---------------------------------------------------------------------------

# Keyword names an audit sink was found not to accept, so the warning is logged
# once rather than on every mutating call.
_audit_sink_dropped: set[str] = set()


def _audit_sink_kwargs(sink: Callable[..., Any], row: dict[str, Any]) -> dict[str, Any]:
    """Narrow an audit row to the keywords the installed sink accepts.

    Args:
        sink: The ``record_audit`` callable.
        row: The audit columns to write.

    Returns:
        The subset of ``row`` the sink can take. The whole row when the sink
        accepts arbitrary keywords or its signature cannot be read.
    """
    try:
        parameters = inspect.signature(sink).parameters
    except (TypeError, ValueError):
        return row

    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return row

    accepted = {name for name in parameters if name != "self"}
    dropped = {key for key in row if key not in accepted}
    if not dropped:
        return row

    unreported = dropped - _audit_sink_dropped
    if unreported:
        _audit_sink_dropped.update(unreported)
        logger.warning(
            "database.agent_db.record_audit does not accept %s; those agent audit "
            "fields will not be recorded",
            ", ".join(sorted(unreported)),
        )
    return {key: value for key, value in row.items() if key in accepted}


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------


def _as_status_code(value: Any) -> int | None:
    """Coerce a response ``code`` field to an HTTP status code.

    Args:
        value: The raw field value.

    Returns:
        The integer status, or None when the field is absent or unusable.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _extract_detail(payload: Any) -> str:
    """Pull the human-readable reason out of a service error payload.

    Args:
        payload: The error payload, usually a dictionary carrying ``message``.

    Returns:
        A single-line reason, empty when the payload carries none.
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()

    if isinstance(payload, Mapping):
        for key in ("message", "error", "detail", "reason", "error_message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        errors = payload.get("errors")
        if isinstance(errors, (list, tuple)) and errors:
            lines: list[str] = []
            for item in errors[:5]:
                if isinstance(item, Mapping):
                    path = item.get("path") or item.get("field") or ""
                    text = item.get("message") or item.get("code") or ""
                    lines.append(f"{path}: {text}".strip(": ").strip())
                else:
                    lines.append(str(item))
            joined = "; ".join(line for line in lines if line)
            if joined:
                return joined
        if isinstance(errors, str) and errors.strip():
            return errors.strip()

    text = str(payload).strip()
    return text[:500]


def _guess_fields(message: str) -> list[str]:
    """Work out which tool arguments an error message is complaining about.

    Args:
        message: The service's own error text.

    Returns:
        Up to six argument names, in the order they appear. Empty when the
        message names none.
    """
    if not message:
        return []

    names: list[str] = []

    missing = _MISSING_FIELDS_PATTERN.search(message)
    if missing:
        for raw in re.split(r"[,\s]+", missing.group(1)):
            cleaned = raw.strip(" .'\"()[]").lower()
            if cleaned and cleaned not in names:
                names.append(cleaned)

    for match in _ARGUMENT_NAME_PATTERN.finditer(message):
        cleaned = match.group(1).lower()
        if cleaned not in names:
            names.append(cleaned)

    return names[:6]
