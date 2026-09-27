# services/flow_executor_service.py
"""
Flow Workflow Executor Service
Executes workflow nodes using internal OpenAlgo services (synchronous Flask version)
"""

import json
import logging
import math
import re
import threading
import time as time_module
import weakref
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import and_

from database.flow_db import (
    add_execution_log,
    create_execution,
    get_execution,
    get_workflow,
    update_execution_status,
)
from services.flow_node_contracts import (
    EXPIRY_DATE_PATTERN as _EXPIRY_DATE_PATTERN,
)
from services.flow_node_contracts import (
    OPTION_OFFSET_PATTERN as _OPTION_OFFSET_PATTERN,
)
from services.flow_node_contracts import (
    VALID_EXPIRY_TYPES,
    VALID_LEG_STRIKE_MODES,
    default_product_for_exchange,
    select_expiry,
)
from services.flow_openalgo_client import FlowOpenAlgoClient, get_flow_client
from utils import real_threading as _real_threading
from utils.constants import VALID_ACTIONS, VALID_EXCHANGES, VALID_PRICE_TYPES, VALID_PRODUCT_TYPES

logger = logging.getLogger(__name__)

# Execution limits
MAX_NODE_DEPTH = 100
MAX_NODE_VISITS = 500

# Logic gates combine the boolean results of their inputs. Wires into these
# nodes are data edges, not control edges — see the edge filter below.
GATE_NODE_TYPES = ("andGate", "orGate", "notGate")
# Nodes that fan out into a TRUE and a FALSE branch. Like a gate, each is
# combinational: one result per run, however many paths reach it.
BRANCHING_NODE_TYPES = (
    "priceCondition",
    "timeCondition",
    "timeWindow",
    "positionCheck",
    "fundCheck",
    "varCondition",
)

# Nodes that place, change or cancel something at the broker. An unresolved
# {{variable}} in one of their order-defining fields is treated as a failure
# rather than being allowed to fall back to a default -- see
# NodeExecutor.unresolved_order_fields.
ORDER_NODE_TYPES = frozenset(
    {
        "placeOrder",
        "smartOrder",
        "optionsOrder",
        "optionsMultiOrder",
        "basketOrder",
        "splitOrder",
        "modifyOrder",
        "cancelOrder",
        "closePositions",
    }
)

OPTION_EXPIRY_NODE_TYPES = frozenset({"optionSymbol", "optionChain", "syntheticFuture"})

# Fields on those nodes that decide what actually reaches the broker. Label-ish
# fields (strategy, strategyTag, outputVariable) are deliberately absent: an
# unresolved reference there is untidy, not dangerous.
ORDER_CRITICAL_FIELDS = frozenset(
    {
        "symbol",
        "exchange",
        "action",
        "quantity",
        "product",
        "priceType",
        "pricetype",
        "price",
        "triggerPrice",
        "splitSize",
        "positionSize",
        "underlying",
        "strike",
        "optionType",
        "expiryDate",
        "orderId",
        "newQuantity",
        "newPrice",
        "newTriggerPrice",
        "orders",
        "legs",
    }
)

# What an unresolved reference looks like after interpolation: WorkflowContext
# returns the original {{...}} text when a path does not resolve.
_UNRESOLVED_PATTERN = re.compile(r"\{\{[^}]*\}\}")
_MISSING_ORDER_VALUE = object()


#: MCX products that list options in the master contract.
#:
#: MCX has no spot instrument, so an option's ATM reference is the near-month
#: future rather than an index level, and there is no separate derivatives
#: segment the way NFO is to NSE -- the future, the option and the quote all
#: live on MCX. option_symbol_service resolves that future itself for every
#: exchange in its NO_SPOT_EXCHANGES set.
MCX_OPTION_UNDERLYINGS = (
    "GOLD",
    "GOLDM",
    "SILVER",
    "SILVERM",
    "CRUDEOIL",
    "CRUDEOILM",
    "NATURALGAS",
    "NATGASMINI",
    "COPPER",
    "ZINC",
    "MCXBULLDEX",
)

#: underlying -> (exchange to quote for the ATM reference, exchange the option
#: trades on). Anything absent is an NSE underlying, which is the overwhelming
#: majority and keeps this table to the exceptions.
OPTION_UNDERLYING_EXCHANGES: dict[str, tuple[str, str]] = {
    "SENSEX": ("BSE_INDEX", "BFO"),
    "BANKEX": ("BSE_INDEX", "BFO"),
    "SENSEX50": ("BSE_INDEX", "BFO"),
    **dict.fromkeys(MCX_OPTION_UNDERLYINGS, ("MCX", "MCX")),
}

DEFAULT_OPTION_EXCHANGES = ("NSE_INDEX", "NFO")

#: Exchange the author may have declared on the node -> the same pair. Only
#: consulted for an underlying the table above does not name, so a stored
#: workflow whose `exchange` still holds the node default cannot reroute a
#: known index.
DECLARED_OPTION_EXCHANGES: dict[str, tuple[str, str]] = {
    "BFO": ("BSE_INDEX", "BFO"),
    "BSE": ("BSE_INDEX", "BFO"),
    "BSE_INDEX": ("BSE_INDEX", "BFO"),
    "NFO": ("NSE_INDEX", "NFO"),
    "NSE": ("NSE_INDEX", "NFO"),
    "NSE_INDEX": ("NSE_INDEX", "NFO"),
    # No-spot exchanges quote and trade on themselves.
    "MCX": ("MCX", "MCX"),
    "CDS": ("CDS", "CDS"),
    "BCD": ("BCD", "BCD"),
    "NCDEX": ("NCDEX", "NCDEX"),
    "NCO": ("NCO", "NCO"),
}


def resolve_option_exchanges(underlying: str, declared: str = "") -> tuple[str, str]:
    """The quote exchange and the option exchange for an options underlying.

    Both options nodes need this pair, and keeping it in one place is what
    stops them drifting apart -- they already carried two copies of a hardcoded
    BSE list, and adding MCX to only one of them would have left the multi-leg
    node placing commodity legs on NFO.

    A named underlying decides on its own. `declared` -- the node's `exchange`
    field -- is the fallback for anything unnamed, which is how an imported
    workflow reaches a commodity or a stock option this table does not list.
    Name first, because the node default ships "NSE_INDEX" and is left untouched
    unless the author changes the dropdown: trusting it would have sent every
    imported SENSEX order to NFO.
    """
    name = (underlying or "").strip().upper()
    if name in OPTION_UNDERLYING_EXCHANGES:
        return OPTION_UNDERLYING_EXCHANGES[name]
    return DECLARED_OPTION_EXCHANGES.get(
        (declared or "").strip().upper(), DEFAULT_OPTION_EXCHANGES
    )


def symbol_prefix_filter(column, prefix: str):
    """Index-friendly "this column starts with `prefix`" predicate.

    `column.like("NIFTY%")` reads better but is the wrong tool here: SQLite's
    LIKE is case-insensitive by default, so it cannot seek the index and pays a
    case-folding comparison on every candidate row - 1460ms against the NFO rows
    of a full master contract, versus 23ms for the half-open range below, which
    compares on the default BINARY collation and seeks. OpenAlgo symbols are
    always upper-case, so the case-insensitivity buys nothing.
    """
    return and_(column >= prefix, column < prefix[:-1] + chr(ord(prefix[-1]) + 1))

# Execution locks to prevent concurrent execution of the same workflow.
#
# WeakValueDictionary, not a plain dict: an entry disappears once no caller
# holds the lock any more, so the registry stays proportional to workflows
# executing right now rather than to every workflow ever executed (issue #1739).
#
# Do NOT replace this with a size-capped dict that evicts entries. Evicting a
# lock a thread is currently holding hands the next caller a brand-new lock, its
# `lock.locked()` guard in execute_workflow passes, and the same workflow runs
# twice concurrently - placing every order in it twice. Weak references cannot
# do that: while any caller holds the lock, it holds a strong reference, so the
# entry is guaranteed to survive and every caller sees the same object.
_workflow_locks: "weakref.WeakValueDictionary[int, threading.Lock]" = (
    weakref.WeakValueDictionary()
)
_locks_mutex = threading.Lock()


# Symbols each workflow has an open market-data subscription for, as
# {workflow_id: {(symbol, exchange, mode), ...}}.
#
# The subscribe nodes open a broker-side subscription and nothing ever closed
# it: the websocket client is a process-wide singleton whose subscription set
# outlives every run, so a workflow reading `{{webhook.symbol}}` accumulated one
# per distinct symbol until the adapter ceiling (1000 x 3) was reached, after
# which new subscriptions from /trading, the sandbox engine and the API began
# failing. Deactivating or deleting the workflow now gives them back.
_workflow_subscriptions: dict[int, set[tuple[str, str, str]]] = {}
_workflow_subscriptions_lock = threading.Lock()


def record_workflow_subscription(
    workflow_id: int | None, symbol: str, exchange: str, mode: str
) -> None:
    """Remember a subscription so it can be released with the workflow."""
    if workflow_id is None:
        return
    with _workflow_subscriptions_lock:
        _workflow_subscriptions.setdefault(workflow_id, set()).add((symbol, exchange, mode))


def release_workflow_subscriptions(workflow_id: int) -> int:
    """Drop every subscription a workflow opened. Returns how many were released.

    Called when a workflow is deactivated or deleted. Safe to call for a
    workflow that never subscribed, and safe to call twice.
    """
    with _workflow_subscriptions_lock:
        entries = _workflow_subscriptions.pop(workflow_id, set())
    if not entries:
        return 0

    try:
        from services.websocket_service import unsubscribe_from_symbols
    except Exception:
        logger.exception("Cannot release subscriptions: websocket service unavailable")
        return 0

    # Resolved once, not per symbol: it is a database read.
    username, broker = _subscription_owner(workflow_id)
    if not username:
        logger.warning(
            f"Workflow {workflow_id} has {len(entries)} subscription(s) but no "
            f"resolvable session to release them from"
        )
        return 0

    released = 0
    for symbol, exchange, mode in entries:
        try:
            ok, _result, _ = unsubscribe_from_symbols(
                username, broker, [{"symbol": symbol, "exchange": exchange}], mode
            )
            released += 1 if ok else 0
        except Exception:
            # One symbol failing must not strand the rest.
            logger.exception(f"Failed to release {mode} on {exchange}:{symbol}")
    logger.info(f"Released {released}/{len(entries)} subscription(s) for workflow {workflow_id}")
    return released


def _subscription_owner(workflow_id: int) -> tuple[str | None, str]:
    """The username and broker whose session holds this workflow's subscriptions."""
    from database.auth_db import get_broker_name, get_username_by_apikey
    from database.flow_db import get_workflow_api_key

    try:
        api_key = get_workflow_api_key(workflow_id)
        if not api_key:
            return None, "unknown"
        return get_username_by_apikey(api_key), get_broker_name(api_key) or "unknown"
    except Exception:
        logger.exception(f"Cannot resolve subscription owner for workflow {workflow_id}")
        return None, "unknown"


def get_workflow_lock(workflow_id: int) -> threading.Lock:
    """Get or create a lock for a workflow.

    Callers must keep the returned lock referenced for as long as they rely on
    it (``lock = get_workflow_lock(id); with lock:``) - which is what keeps the
    registry entry alive. Discarding the reference and re-fetching mid-critical
    section would not be safe.
    """
    with _locks_mutex:
        lock = _workflow_locks.get(workflow_id)
        if lock is None:
            lock = threading.Lock()
            _workflow_locks[workflow_id] = lock
        return lock


def parse_time_string(
    time_str: str, default_hour: int = 9, default_minute: int = 15
) -> tuple[int, int, int]:
    """Parse a time string in HH:MM or HH:MM:SS format"""
    if not time_str or not isinstance(time_str, str):
        return (default_hour, default_minute, 0)

    try:
        parts = time_str.strip().split(":")
        if not parts:
            return (default_hour, default_minute, 0)

        hour = int(parts[0]) if parts[0].isdigit() else default_hour
        minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else default_minute
        second = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        second = max(0, min(59, second))

        return (hour, minute, second)
    except (ValueError, AttributeError, IndexError):
        return (default_hour, default_minute, 0)


class WorkflowContext:
    """Context for storing variables during workflow execution"""

    def __init__(self, workflow_id: int | None = None):
        self.variables: dict[str, Any] = {}
        self.condition_results: dict[str, bool] = {}
        # Which workflow this run belongs to, so a subscription it opens can be
        # released when that workflow is deactivated or deleted.
        self.workflow_id = workflow_id

    def set_variable(self, name: str, value: Any):
        """Store a variable"""
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a variable value"""
        return self.variables.get(name, default)

    def set_condition_result(self, node_id: str, result: bool):
        """Store a condition result for a node"""
        self.condition_results[node_id] = result

    def get_condition_result(self, node_id: str) -> bool | None:
        """Get the condition result for a node"""
        return self.condition_results.get(node_id)

    def _get_builtin_variable(self, name: str) -> str | None:
        """Get built-in system variables"""
        now = datetime.now()
        builtins = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "year": now.strftime("%Y"),
            "month": now.strftime("%m"),
            "day": now.strftime("%d"),
            "hour": now.strftime("%H"),
            "minute": now.strftime("%M"),
            "second": now.strftime("%S"),
            "weekday": now.strftime("%A"),
            "iso_timestamp": now.isoformat(),
            # Numeric weekday, because varCondition compares numbers and
            # "Thursday" cannot be used in a range test.
            "weekday_num": str(now.isoweekday()),  # 1 = Monday
            "quarter": str((now.month - 1) // 3 + 1),
            "week_of_year": str(now.isocalendar().week),
            "day_of_year": str(now.timetuple().tm_yday),
            # The trading session date, which differs from `date` between
            # midnight and the 03:00 IST rollover. `date` is left as the plain
            # calendar date for back-compatibility.
            "session_date": self._session_date(),
        }
        return builtins.get(name)

    @staticmethod
    def _session_date() -> str:
        """The trading session date, falling back to the local calendar date.

        The fallback is wrong by up to three hours of session labelling, so it
        is logged rather than swallowed: silently returning a different date
        than the method promises is the kind of failure that only shows up as a
        strategy acting on the wrong day.
        """
        try:
            from utils.session import get_trading_session_date

            return get_trading_session_date()
        except Exception:
            logger.exception(
                "Could not resolve the trading session date; using the local calendar date"
            )
            return datetime.now().date().isoformat()

    # Path segment: either a dotted key ([^.[\]]+) or a bracketed integer index (\[\d+\])
    _PATH_SEGMENT_RE = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")
    _WHOLE_TOKEN_RE = re.compile(r"^\{\{\s*([^}]+?)\s*\}\}$")

    # Sentinel distinguishing "path did not resolve" from a legitimately None value.
    _UNRESOLVED = object()

    def _walk_path(self, var_path: str) -> Any:
        """Walk a dotted/bracketed variable path against stored variables and
        return the raw Python object (not stringified) - or `_UNRESOLVED` if
        any segment is missing. Shared by `interpolate` (which stringifies
        the result for text substitution) and `resolve_raw` (which returns
        the object itself, needed to pass a list/dict between nodes without
        a lossy str()-repr round-trip - see execute_indicator's nested mode).
        """
        value = self.variables
        for seg in self._PATH_SEGMENT_RE.finditer(var_path):
            key, idx = seg.group(1), seg.group(2)
            if key is not None:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return self._UNRESOLVED
            else:
                i = int(idx)
                if isinstance(value, (list, tuple)) and -len(value) <= i < len(value):
                    value = value[i]
                else:
                    return self._UNRESOLVED
            if value is None:
                return self._UNRESOLVED
        return value

    def resolve_raw(self, text: str) -> Any:
        """Resolve a string that is exactly one `{{path}}` token to the raw
        stored object (list/dict/number), bypassing string interpolation.

        Falls back to `interpolate(text)` (a string) when `text` isn't a
        single whole-token reference (e.g. contains surrounding text, or
        isn't a `{{...}}` reference at all) or the path doesn't resolve.
        """
        if not isinstance(text, str):
            return text
        m = self._WHOLE_TOKEN_RE.match(text)
        if m:
            var_path = m.group(1).strip()
            if self._get_builtin_variable(var_path) is None:
                value = self._walk_path(var_path)
                if value is not self._UNRESOLVED:
                    return value
        return self.interpolate(text)

    def interpolate(self, text: str) -> str:
        """Replace {{variable}} patterns with actual values.

        Supports dict key access (a.b.c) and list/tuple index access (a.b[0], a[0][1]).
        """
        if not isinstance(text, str):
            return text

        def replacer(match):
            var_path = match.group(1).strip()

            # Built-in variables — match only as a single whole token
            builtin_value = self._get_builtin_variable(var_path)
            if builtin_value is not None:
                return builtin_value

            value = self._walk_path(var_path)
            if value is self._UNRESOLVED:
                return match.group(0)
            return str(value)

        return re.sub(r"\{\{([^}]+)\}\}", replacer, text)


class RuntimeOrderResolver:
    """Resolve one order payload without turning supplied bad data into defaults.

    Flow's general accessors are deliberately forgiving because display and
    data nodes often have useful legacy defaults.  That behavior is unsafe at
    an order boundary: an interpolated typo must not become quantity ``1`` or a
    broker mapper's MARKET fallback.  This resolver uses a default only when no
    supported key is present; once a value is supplied, it must resolve and
    validate on its own merits.
    """

    def __init__(self, context: WorkflowContext, data: dict, label: str):
        self.context = context
        self.data = data
        self.label = label

    def value(
        self,
        key: str,
        *,
        default: Any = _MISSING_ORDER_VALUE,
        aliases: tuple[str, ...] = (),
    ) -> Any:
        for candidate in (key, *aliases):
            if candidate not in self.data:
                continue
            raw = self.data[candidate]
            resolved = self.context.resolve_raw(raw) if isinstance(raw, str) else raw
            if isinstance(resolved, str) and _UNRESOLVED_PATTERN.search(resolved):
                raise ValueError(f"{candidate} has unresolved value {resolved!r}")
            return resolved
        if default is _MISSING_ORDER_VALUE:
            raise ValueError(f"{key} is required")
        return default

    def text(
        self,
        key: str,
        *,
        default: Any = _MISSING_ORDER_VALUE,
        aliases: tuple[str, ...] = (),
    ) -> str:
        value = self.value(key, default=default, aliases=aliases)
        if not isinstance(value, str):
            raise ValueError(f"{key} must resolve to text, got {value!r}")
        text = value.strip()
        if not text:
            raise ValueError(f"{key} must not be blank")
        return text

    def enum(
        self,
        key: str,
        allowed: list[str] | frozenset[str],
        *,
        default: Any = _MISSING_ORDER_VALUE,
        aliases: tuple[str, ...] = (),
    ) -> str:
        canonical = self.text(key, default=default, aliases=aliases).upper()
        if canonical not in allowed:
            raise ValueError(
                f"{key} must be one of {', '.join(sorted(allowed))}, got {canonical!r}"
            )
        return canonical

    def number(
        self,
        key: str,
        *,
        default: Any = _MISSING_ORDER_VALUE,
        aliases: tuple[str, ...] = (),
    ) -> float:
        value = self.value(key, default=default, aliases=aliases)
        if isinstance(value, bool):
            raise ValueError(f"{key} must be numeric, got boolean {value!r}")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{key} must not be blank")
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be numeric, got {value!r}") from exc
        if not math.isfinite(number):
            raise ValueError(f"{key} must be finite, got {value!r}")
        return number

    def integer(
        self,
        key: str,
        *,
        default: Any = _MISSING_ORDER_VALUE,
        aliases: tuple[str, ...] = (),
        minimum: int | None = None,
    ) -> int:
        number = self.number(key, default=default, aliases=aliases)
        if minimum is not None and number < minimum:
            qualifier = "non-negative" if minimum == 0 else f"at least {minimum}"
            raise ValueError(f"{key} must be {qualifier}, got {number}")
        return int(number)


def _optional_leg_text(resolver: RuntimeOrderResolver, key: str) -> str:
    """Read a leg field that may be absent or blank, but must be text if given.

    ``RuntimeOrderResolver.text`` rejects a blank value, which is right for a
    required field and wrong for an optional override - an omitted per-leg
    expiry has to mean "inherit the node's", not "reject the leg".
    """
    value = resolver.value(key, default="")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must resolve to text, got {value!r}")
    return value.strip()


class NodeExecutor:
    """Executes individual workflow nodes"""

    def __init__(
        self,
        client: FlowOpenAlgoClient,
        context: WorkflowContext,
        logs: list,
        default_strategy: str = "flow_workflow",
    ):
        self.client = client
        self.context = context
        self.logs = logs
        # Tag applied to every order this workflow places, so trades can be
        # attributed back to the strategy that produced them (the tradebook
        # carries this field). Defaults to the workflow's own name; a node may
        # override it with `strategyTag`.
        self.default_strategy = default_strategy or "flow_workflow"
        # Nodes that reported failure during this run. A non-empty list makes
        # the run `failed`; previously every run was recorded as `completed`
        # unless a handler raised, so a broker rejection returned HTTP 200
        # "Workflow executed successfully".
        self.errors: list[dict] = []

    def strategy_tag(self, node_data: dict) -> str:
        """Strategy label for an order node.

        Uses `strategyTag`, not `strategy`: optionsMultiOrder already uses
        `strategy` for the structure type (straddle / iron_condor / custom).
        """
        return self.get_str(node_data, "strategyTag", "") or self.default_strategy

    def log(self, message: str, level: str = "info"):
        """Add log entry"""
        self.logs.append({"time": datetime.now().isoformat(), "message": message, "level": level})
        if level == "error":
            logger.error(message)
        else:
            logger.info(message)

    def store_output(self, node_data: dict, result: Any):
        """Store result in output variable if configured"""
        output_var = node_data.get("outputVariable")
        if output_var and output_var.strip():
            self.context.set_variable(output_var.strip(), result)
            self.log(f"Stored result in variable: {output_var}")

    def unresolved_order_fields(self, node_data: dict) -> list[tuple[str, str]]:
        """Order-defining fields still holding an unresolved {{reference}}.

        Interpolation is deliberately forgiving: an unknown path passes the
        literal `{{name}}` text through rather than raising. For most fields
        that is the right call, but on an order node it was silently dangerous
        -- `get_int` cannot parse `{{webhook.qty}}`, so it returned its default
        of 1, and `get_str` handed the literal text to the broker mapper, which
        fell back to MARKET. A webhook that simply omitted a key therefore
        produced a successful order for the wrong size at the wrong price type,
        with nothing in the run to say so.

        Checked before dispatch so the node fails instead of the broker call
        being made with substituted values.
        """
        found: list[tuple[str, str]] = []
        for key in ORDER_CRITICAL_FIELDS:
            raw = node_data.get(key)
            if not isinstance(raw, str) or "{{" not in raw:
                continue
            resolved = self.context.resolve_raw(raw)
            if isinstance(resolved, str) and _UNRESOLVED_PATTERN.search(resolved):
                found.append((key, resolved))
        return sorted(found)

    def unresolved_error(self, node_type: str, fields: list[tuple[str, str]]) -> dict:
        """The failure result for a node blocked by unresolved references."""
        detail = ", ".join(f"{key}={text!r}" for key, text in fields)
        message = (
            f"{node_type} has unresolved variable(s) in {detail}. "
            "Refusing to send it with substituted values."
        )
        self.log(message, "error")
        return {"status": "error", "message": message, "unresolved": [f for f, _ in fields]}

    def option_expiry_error(self, node_type: str, node_data: dict) -> dict | None:
        """Reject unresolved or invalid option expiry inputs before a client call."""
        unresolved = []
        for field in ("underlying", "expiryDate"):
            raw = node_data.get(field)
            if isinstance(raw, str) and "{{" in raw:
                resolved = self.context.interpolate(raw)
                if _UNRESOLVED_PATTERN.search(resolved):
                    unresolved.append((field, resolved))
        if unresolved:
            return self.unresolved_error(node_type, unresolved)

        underlying = self.get_str(node_data, "underlying", "").strip()
        expiry_date = self.get_str(node_data, "expiryDate", "").strip()
        if not underlying:
            message = f"{node_type} needs a resolved underlying before it can request option data."
            self.log(message, "error")
            return {"status": "error", "message": message}

        from services.option_symbol_service import parse_underlying_symbol

        _, embedded_expiry = parse_underlying_symbol(underlying)
        has_explicit_expiry = bool(expiry_date)
        needs_expiry = node_type == "syntheticFuture" or has_explicit_expiry or embedded_expiry is None
        if needs_expiry and not _EXPIRY_DATE_PATTERN.fullmatch(expiry_date.upper()):
            message = f"{node_type} needs a resolved expiryDate in DDMMMYY format before it can run."
            self.log(message, "error")
            return {"status": "error", "message": message}
        return None

    def get_str(self, node_data: dict, key: str, default: str = "") -> str:
        """Get interpolated string value from node data"""
        value = node_data.get(key, default)
        return self.context.interpolate(str(value)) if value else default

    def get_int(self, node_data: dict, key: str, default: int = 0) -> int:
        """Get interpolated integer value from node data"""
        value = node_data.get(key)
        if value is None or value == "":
            return default
        if isinstance(value, str):
            interpolated = self.context.interpolate(value)
            try:
                return int(float(interpolated))
            except (ValueError, TypeError):
                return default
        return int(value)

    def get_float(self, node_data: dict, key: str, default: float = 0.0) -> float:
        """Get interpolated float value from node data"""
        value = node_data.get(key)
        if value is None or value == "":
            return default
        if isinstance(value, str):
            interpolated = self.context.interpolate(value)
            try:
                return float(interpolated)
            except (ValueError, TypeError):
                return default
        return float(value)

    def runtime_order_error(self, label: str, error: ValueError) -> dict:
        """Return one consistent fail-closed result for an unusable order value."""
        message = f"{label} has invalid runtime order data: {error}"
        self.log(message, "error")
        return {"status": "error", "message": message}

    def resolve_standard_order(
        self,
        node_data: dict,
        label: str,
        *,
        allow_zero_quantity: bool = False,
    ) -> dict[str, Any]:
        """Resolve the fields shared by regular, smart, and split orders."""
        values = RuntimeOrderResolver(self.context, node_data, label)
        quantity_minimum = 0 if allow_zero_quantity else 1
        # The exchange decides the product default, so it is read out before the
        # dict is built -- a node whose author never touched Product sends NRML
        # on a derivative segment and MIS on cash. Symbol is still resolved
        # first, so a node with several problems reports the same one it always
        # did.
        # Upper-cased for the same reason every enum field is: an alert does not
        # control its own casing. TradingView sends whatever the chart's ticker
        # carries, and the symbol lookup is exact, so 'reliance' fails with
        # "Symbol not found" while 'RELIANCE' resolves. Every OpenAlgo symbol is
        # upper case, so this cannot collide with a real one.
        symbol = values.text("symbol").upper()
        exchange = values.enum("exchange", VALID_EXCHANGES, default="NSE")
        resolved = {
            "symbol": symbol,
            "exchange": exchange,
            "action": values.enum("action", VALID_ACTIONS, default="BUY"),
            "quantity": values.integer("quantity", default=1, minimum=quantity_minimum),
            "price_type": values.enum("priceType", VALID_PRICE_TYPES, default="MARKET"),
            "product": values.enum(
                "product", VALID_PRODUCT_TYPES, default=default_product_for_exchange(exchange)
            ),
            "price": values.number("price", default=0.0),
            "trigger_price": values.number("triggerPrice", default=0.0),
        }
        invalid = self._invalid_price_reason(
            resolved["price_type"], resolved["price"], resolved["trigger_price"]
        )
        if invalid:
            raise ValueError(invalid)
        return resolved

    # === Order Nodes ===

    def execute_place_order(self, node_data: dict) -> dict:
        """Execute Place Order node"""
        try:
            order = self.resolve_standard_order(node_data, "Place order")
        except ValueError as exc:
            return self.runtime_order_error("Place order", exc)

        self.log(
            f"Placing order: {order['symbol']} {order['action']} qty={order['quantity']}"
        )
        result = self.client.place_order(
            symbol=order["symbol"],
            exchange=order["exchange"],
            action=order["action"],
            quantity=order["quantity"],
            price_type=order["price_type"],
            product_type=order["product"],
            price=order["price"],
            trigger_price=order["trigger_price"],
            strategy=self.strategy_tag(node_data),
        )
        self.log(
            f"Order result: {result}", "info" if result.get("status") == "success" else "error"
        )
        self.store_output(node_data, result)
        return result

    def execute_smart_order(self, node_data: dict) -> dict:
        """Execute Smart Order node"""
        try:
            order = self.resolve_standard_order(
                node_data, "Smart order", allow_zero_quantity=True
            )
            values = RuntimeOrderResolver(self.context, node_data, "Smart order")
            position_size = values.integer("positionSize", default=0)
        except ValueError as exc:
            return self.runtime_order_error("Smart order", exc)

        self.log(f"Placing smart order: {order['symbol']} {order['action']}")
        result = self.client.place_smart_order(
            symbol=order["symbol"],
            exchange=order["exchange"],
            action=order["action"],
            quantity=order["quantity"],
            position_size=position_size,
            price_type=order["price_type"],
            product_type=order["product"],
            price=order["price"],
            trigger_price=order["trigger_price"],
            strategy=self.strategy_tag(node_data),
        )
        self.log(
            f"Smart order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    # Exchange lot sizes are revised by the exchanges periodically, so a
    # hardcoded table goes stale silently and mis-sizes every order placed
    # against it. The master contract is refreshed daily and is authoritative;
    # the table below is only a last resort for an unseeded database.
    _FALLBACK_LOT_SIZES = {
        "NIFTY": 65,
        "BANKNIFTY": 30,
        "FINNIFTY": 60,
        "MIDCPNIFTY": 120,
        "NIFTYNXT50": 25,
        "SENSEX": 20,
        "BANKEX": 30,
        "SENSEX50": 25,
    }

    @staticmethod
    def _invalid_price_reason(price_type: str, price: float, trigger_price: float) -> str | None:
        """Why this price type cannot be sent, or None when it is usable.

        A LIMIT or SL order whose price never reached the broker executes at an
        unintended level, so it is refused rather than sent with a zero.
        """
        price_type = (price_type or "MARKET").upper()
        if not math.isfinite(price):
            return f"{price_type} order needs a finite price, got {price}"
        if not math.isfinite(trigger_price):
            return f"{price_type} order needs a finite trigger price, got {trigger_price}"
        if price_type in ("LIMIT", "SL") and price <= 0:
            return f"{price_type} order needs a positive price, got {price}"
        if price_type in ("SL", "SL-M") and trigger_price <= 0:
            return f"{price_type} order needs a positive trigger price, got {trigger_price}"
        return None

    class LotSizeUnavailable(RuntimeError):
        """The lot size could not be determined, so quantity cannot be computed."""

    def _resolve_lot_size(self, underlying: str, fo_exchange: str) -> int:
        """Lot size for an underlying, from the master contract.

        Fails closed. A lookup error means the lot size is *unknown*, and
        guessing it sizes a real order wrongly - the fallback table is used only
        when the master contract is genuinely unseeded for this exchange, and
        only for an underlying whose lot size we ship.

        Raises:
            LotSizeUnavailable: the lot size cannot be established.
        """
        from database.symbol import SymToken, db_session
        from database.token_db_enhanced import extract_underlying_from_symbol

        try:
            row = (
                db_session.query(SymToken.lotsize)
                .filter(
                    SymToken.name == underlying,
                    SymToken.exchange == fo_exchange,
                    SymToken.lotsize.isnot(None),
                    SymToken.lotsize > 0,
                )
                .first()
            )
            if row and row[0]:
                return int(row[0])

            # `name` holds the underlying root only where the broker's master
            # contract put it there. Some ship the contract description instead
            # ("NIFTY 11 Aug 26 24450 CE"), so `name == "NIFTY"` matches nothing
            # and an order that should have gone through fails. Rather than
            # correct this in each of 35+ broker plugins, fall back to the
            # OpenAlgo symbol, which OpenAlgo normalizes itself and so reads the
            # same on every broker - the same reason expiry_service and
            # option_symbol_service key off it.
            #
            # The prefix alone is not sufficient: symbols starting "NIFTY" also
            # include NIFTYNXT50, whose lot size differs (25 vs 65). Confirm each
            # candidate with the same extractor the underlying dropdown uses, so
            # the value offered and the value resolved come from one function.
            candidates = (
                db_session.query(SymToken.symbol, SymToken.lotsize)
                .filter(
                    symbol_prefix_filter(SymToken.symbol, underlying),
                    SymToken.exchange == fo_exchange,
                    SymToken.lotsize.isnot(None),
                    SymToken.lotsize > 0,
                )
                .yield_per(200)
            )
            for symbol, lotsize in candidates:
                if extract_underlying_from_symbol(symbol, fo_exchange) == underlying:
                    return int(lotsize)
            # Distinguish "this exchange has no contracts loaded" from "this
            # underlying is not one of them". Only the former is a fallback case.
            exchange_seeded = (
                db_session.query(SymToken.id).filter(SymToken.exchange == fo_exchange).first()
                is not None
            )
        except Exception as exc:
            db_session.rollback()
            logger.exception(f"Lot size lookup failed for {underlying} on {fo_exchange}")
            raise self.LotSizeUnavailable(
                f"Could not read the lot size for {underlying} on {fo_exchange}. "
                "Refusing to size an order on a guess."
            ) from exc
        finally:
            # Flow runs in background threads with no Flask app context, so the
            # per-request teardown never fires and this session would stay bound
            # to the thread holding its connection.
            db_session.remove()

        if exchange_seeded:
            raise self.LotSizeUnavailable(
                f"{underlying} has no contract on {fo_exchange} in the master contract. "
                "Check the symbol, or re-download the master contract."
            )
        fallback = self._FALLBACK_LOT_SIZES.get(underlying)
        if fallback is None:
            raise self.LotSizeUnavailable(
                f"The master contract has no {fo_exchange} contracts loaded and no "
                f"built-in lot size for {underlying}. Download the master contract first."
            )
        self.log(
            f"Master contract has no {fo_exchange} contracts loaded; using the built-in "
            f"lot size {fallback} for {underlying}",
            "warning",
        )
        return fallback

    def execute_options_order(self, node_data: dict) -> dict:
        """Execute Options Order node"""
        try:
            values = RuntimeOrderResolver(self.context, node_data, "Options order")
            underlying = values.text("underlying", default="NIFTY").upper()
            expiry_type = values.text("expiryType", default="current_week").lower()
            # A leg has always been able to name its own date; the node could
            # only pick one of the four relative types, so a webhook naming a
            # far contract had no way to say so. An explicit date wins, and the
            # relative type stays the default for the common case.
            # `_optional_leg_text`, not `text`: `text` rejects a blank value, which
            # is right for a required field and wrong for an optional override. It
            # raises on its own default, so `text("expiryDate", default="")` failed
            # every options order whose author had not set one -- which is all of
            # them, since neither the panel nor the node defaults write the key.
            expiry_date_input = _optional_leg_text(values, "expiryDate").upper()
            # The editor offers a single Expiry control that holds either form,
            # so a DDMMMYY value arriving under expiryType is an explicit date
            # rather than a relative type. The separate expiryDate key stays
            # available for callers that would rather send the two apart.
            if not expiry_date_input and _EXPIRY_DATE_PATTERN.fullmatch(expiry_type.upper()):
                expiry_date_input = expiry_type.upper()
            if expiry_date_input and not _EXPIRY_DATE_PATTERN.fullmatch(expiry_date_input):
                raise ValueError(
                    "expiryDate must be in DDMMMYY format such as 28OCT25, "
                    f"got {expiry_date_input!r}"
                )
            if not expiry_date_input and expiry_type not in VALID_EXPIRY_TYPES:
                raise ValueError(
                    "expiryType must be one of "
                    f"{', '.join(sorted(VALID_EXPIRY_TYPES))}, got {expiry_type!r}"
                )
            quantity = values.integer("quantity", default=1, minimum=1)
            offset = values.text("offset", default="ATM").upper()
            if not _OPTION_OFFSET_PATTERN.fullmatch(offset):
                raise ValueError(
                    f"offset must be ATM, ITM1-ITM50, or OTM1-OTM50, got {offset!r}"
                )
            option_type = values.enum("optionType", frozenset({"CE", "PE"}), default="CE")
            action = values.enum("action", VALID_ACTIONS, default="BUY")
            price_type = values.enum("priceType", VALID_PRICE_TYPES, default="MARKET")
            product = values.enum("product", VALID_PRODUCT_TYPES, default="NRML")
            split_size = values.integer("splitSize", default=0, minimum=0)
            price = values.number("price", default=0.0)
            trigger_price = values.number("triggerPrice", default=0.0)
            if "exchange" in node_data:
                values.enum("exchange", VALID_EXCHANGES)
            invalid = self._invalid_price_reason(price_type, price, trigger_price)
            if invalid:
                raise ValueError(invalid)
        except ValueError as exc:
            return self.runtime_order_error("Options order", exc)

        self.log(f"Placing options order: {underlying} {option_type} {offset}")

        underlying_exchange, fo_exchange = resolve_option_exchanges(
            underlying, self.get_str(node_data, "exchange", "")
        )

        try:
            lot_size = self._resolve_lot_size(underlying, fo_exchange)
        except self.LotSizeUnavailable as exc:
            error_result = {"status": "error", "message": str(exc)}
            self.log(f"Options order failed: {exc}", "error")
            return error_result
        total_quantity = quantity * lot_size
        self.log(f"Lot size for {underlying}: {lot_size} -> {quantity} lot(s) = {total_quantity}")

        # An explicit date is used as given; only a relative type is looked up.
        expiry_date = expiry_date_input or self._resolve_expiry_date(
            underlying, fo_exchange, expiry_type
        )
        if not expiry_date:
            error_result = {
                "status": "error",
                "message": f"Could not resolve expiry for {expiry_type}",
            }
            self.log(f"Options order failed: {error_result['message']}", "error")
            return error_result

        self.log(
            f"Resolved expiry: {expiry_date_input or expiry_type} -> {expiry_date}"
        )

        result = self.client.options_order(
            underlying=underlying,
            exchange=underlying_exchange,
            action=action,
            quantity=total_quantity,
            expiry_date=expiry_date,
            offset=offset,
            option_type=option_type,
            price_type=price_type,
            product=product,
            price=price,
            trigger_price=trigger_price,
            splitsize=split_size,
            strategy=self.strategy_tag(node_data),
        )
        self.log(
            f"Options order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_options_multi_order(self, node_data: dict) -> dict:
        """Execute Options Multi-Order node (multi-leg strategy)"""
        # Debug: log node_data keys to understand structure
        self.log(f"Options multi-order node_data keys: {list(node_data.keys())}")

        try:
            values = RuntimeOrderResolver(self.context, node_data, "Options multi-order")
            underlying = values.text("underlying", default="NIFTY").upper()
            expiry_type = values.text("expiryType", default="current_week").lower()
            # As on the single-leg node: an explicit DDMMMYY date wins, the
            # relative type remains the default. A leg may still override both.
            # `_optional_leg_text`, not `text`: `text` rejects a blank value, which
            # is right for a required field and wrong for an optional override. It
            # raises on its own default, so `text("expiryDate", default="")` failed
            # every options order whose author had not set one -- which is all of
            # them, since neither the panel nor the node defaults write the key.
            expiry_date_input = _optional_leg_text(values, "expiryDate").upper()
            # The editor offers a single Expiry control that holds either form,
            # so a DDMMMYY value arriving under expiryType is an explicit date
            # rather than a relative type. The separate expiryDate key stays
            # available for callers that would rather send the two apart.
            if not expiry_date_input and _EXPIRY_DATE_PATTERN.fullmatch(expiry_type.upper()):
                expiry_date_input = expiry_type.upper()
            if expiry_date_input and not _EXPIRY_DATE_PATTERN.fullmatch(expiry_date_input):
                raise ValueError(
                    "expiryDate must be in DDMMMYY format such as 28OCT25, "
                    f"got {expiry_date_input!r}"
                )
            if not expiry_date_input and expiry_type not in VALID_EXPIRY_TYPES:
                raise ValueError(
                    "expiryType must be one of "
                    f"{', '.join(sorted(VALID_EXPIRY_TYPES))}, got {expiry_type!r}"
                )
            # Frontend uses ``strategy``; ``strategyType`` is a legacy alias.
            strategy_type = values.text(
                "strategy", default="custom", aliases=("strategyType",)
            ).lower()
            action = values.enum("action", VALID_ACTIONS, default="SELL")
            quantity_lots = values.integer("quantity", default=1, minimum=1)
            product = values.enum("product", VALID_PRODUCT_TYPES, default="NRML")
            strangle_width = values.text("strangleWidth", default="OTM2").upper()
            if not _OPTION_OFFSET_PATTERN.fullmatch(strangle_width):
                raise ValueError(
                    "strangleWidth must be ATM, ITM1-ITM50, or OTM1-OTM50, "
                    f"got {strangle_width!r}"
                )
            multi_price_type = values.enum(
                "priceType", VALID_PRICE_TYPES, default="MARKET"
            )
            multi_price = values.number("price", default=0.0)
            multi_trigger_price = values.number("triggerPrice", default=0.0)
            if "exchange" in node_data:
                values.enum("exchange", VALID_EXCHANGES)
            if strategy_type != "custom":
                if multi_price_type not in {"MARKET", "LIMIT"}:
                    raise ValueError(
                        "generated option strategies support only MARKET and LIMIT price types"
                    )
                invalid = self._invalid_price_reason(
                    multi_price_type, multi_price, multi_trigger_price
                )
                if invalid:
                    raise ValueError(invalid)
        except ValueError as exc:
            return self.runtime_order_error("Options multi-order", exc)

        normalized_custom_legs: list[dict[str, Any]] | None = None
        if strategy_type == "custom":
            try:
                raw_legs = values.value("legs", aliases=("orderLegs",))
                if not isinstance(raw_legs, list) or not raw_legs:
                    raise ValueError("legs must resolve to a non-empty list of objects")
                if any(not isinstance(leg, dict) for leg in raw_legs):
                    raise ValueError("every resolved leg must be an object")

                normalized_custom_legs = []
                for index, leg in enumerate(raw_legs, start=1):
                    leg_values = RuntimeOrderResolver(
                        self.context, leg, f"Options multi-order leg {index}"
                    )
                    try:
                        # A leg picks its strike one of two ways. An offset is
                        # re-resolved against the live underlying on every run,
                        # which is what a repeating workflow wants. An absolute
                        # strike names one contract and is used as given, which
                        # suits a one-shot or manually built spread.
                        strike_mode = leg_values.enum(
                            "strikeMode",
                            VALID_LEG_STRIKE_MODES,
                            default="OFFSET",
                        )
                        offset: str | None = None
                        strike: float | None = None
                        if strike_mode == "STRIKE":
                            strike = leg_values.number("strike")
                            if strike <= 0:
                                raise ValueError(
                                    f"strike must be a positive number, got {strike}"
                                )
                        else:
                            offset = leg_values.text("offset").upper()
                            if not _OPTION_OFFSET_PATTERN.fullmatch(offset):
                                raise ValueError(
                                    "offset must be ATM, ITM1-ITM50, or "
                                    f"OTM1-OTM50, got {offset!r}"
                                )
                        # A leg may override the node expiry, which is what
                        # makes a calendar or diagonal spread expressible.
                        # Either an explicit DDMMMYY date or a relative type;
                        # the date is resolved once the exchange is known.
                        leg_expiry_date = _optional_leg_text(leg_values, "expiry").upper()
                        if leg_expiry_date and not _EXPIRY_DATE_PATTERN.fullmatch(
                            leg_expiry_date
                        ):
                            raise ValueError(
                                "expiry must be in DDMMMYY format such as 28OCT25, "
                                f"got {leg_expiry_date!r}"
                            )
                        leg_expiry_type = _optional_leg_text(
                            leg_values, "expiryType"
                        ).lower()
                        if leg_expiry_type and leg_expiry_type not in VALID_EXPIRY_TYPES:
                            raise ValueError(
                                "expiryType must be one of "
                                f"{', '.join(sorted(VALID_EXPIRY_TYPES))}, "
                                f"got {leg_expiry_type!r}"
                            )
                        option_type = leg_values.enum(
                            "optionType", frozenset({"CE", "PE"})
                        )
                        leg_action = leg_values.enum("action", VALID_ACTIONS)
                        leg_quantity = leg_values.integer("quantity", minimum=1)
                        leg_product = leg_values.enum(
                            "product", VALID_PRODUCT_TYPES, default=product
                        )
                        leg_price_type = leg_values.enum(
                            "priceType",
                            VALID_PRICE_TYPES,
                            default=multi_price_type,
                            aliases=("pricetype",),
                        )
                        leg_price = leg_values.number("price", default=multi_price)
                        leg_trigger = leg_values.number(
                            "triggerPrice",
                            default=multi_trigger_price,
                            aliases=("trigger_price",),
                        )
                        leg_split_size = leg_values.integer(
                            "splitSize", default=0, aliases=("splitsize",), minimum=0
                        )
                        invalid = self._invalid_price_reason(
                            leg_price_type, leg_price, leg_trigger
                        )
                        if invalid:
                            raise ValueError(invalid)
                    except ValueError as exc:
                        raise ValueError(f"leg {index}: {exc}") from exc
                    normalized_custom_legs.append(
                        {
                            "offset": offset,
                            "strike": strike,
                            "expiry_date": leg_expiry_date,
                            "expiry_type": leg_expiry_type,
                            "option_type": option_type,
                            "action": leg_action,
                            "quantity_lots": leg_quantity,
                            "pricetype": leg_price_type,
                            "product": leg_product,
                            "price": leg_price,
                            "trigger_price": leg_trigger,
                            "splitsize": leg_split_size,
                        }
                    )
            except ValueError as exc:
                return self.runtime_order_error("Options multi-order", exc)

        self.log(
            f"Strategy: {strategy_type}, Action: {action}, Quantity: {quantity_lots} lots, Product: {product}"
        )

        underlying_exchange, fo_exchange = resolve_option_exchanges(
            underlying, self.get_str(node_data, "exchange", "")
        )

        # Same master-contract lookup the single-leg options node uses. A second
        # hardcoded table here drifted the same way the first one had: it still
        # claimed FINNIFTY was 65 where the contract says 60.
        try:
            lot_size = self._resolve_lot_size(underlying, fo_exchange)
        except self.LotSizeUnavailable as exc:
            error_result = {"status": "error", "message": str(exc)}
            self.log(f"Options multi-order failed: {exc}", "error")
            return error_result
        total_quantity = quantity_lots * lot_size
        self.log(
            f"Lot size for {underlying}: {lot_size} -> {quantity_lots} lot(s) = {total_quantity}"
        )

        # Resolve expiry date
        # An explicit date is used as given; only a relative type is looked up.
        expiry_date = expiry_date_input or self._resolve_expiry_date(
            underlying, fo_exchange, expiry_type
        )
        if not expiry_date:
            error_result = {
                "status": "error",
                "message": f"Could not resolve expiry for {expiry_type}",
            }
            self.log(f"Options multi-order failed: {error_result['message']}", "error")
            return error_result

        self.log(
            f"Resolved expiry: {expiry_date_input or expiry_type} -> {expiry_date}"
        )

        # Generate legs based on strategy type if no custom legs provided
        legs = []
        if normalized_custom_legs is not None:
            # A relative per-leg expiry costs a master-contract lookup, so legs
            # sharing one expiry type resolve it once.
            leg_expiry_cache: dict[str, str] = {}
            for index, leg in enumerate(normalized_custom_legs, start=1):
                leg_expiry = leg["expiry_date"]
                expiry_type_override = leg["expiry_type"]
                if not leg_expiry and expiry_type_override:
                    leg_expiry = leg_expiry_cache.get(expiry_type_override, "")
                    if not leg_expiry:
                        resolved = self._resolve_expiry_date(
                            underlying, fo_exchange, expiry_type_override
                        )
                        if not resolved:
                            message = (
                                f"leg {index}: could not resolve expiry for "
                                f"{expiry_type_override}"
                            )
                            self.log(f"Options multi-order failed: {message}", "error")
                            return {"status": "error", "message": message}
                        leg_expiry_cache[expiry_type_override] = resolved
                        leg_expiry = resolved

                prepared = {
                    key: value
                    for key, value in leg.items()
                    if key not in ("quantity_lots", "expiry_date", "expiry_type")
                }
                prepared["quantity"] = leg["quantity_lots"] * lot_size
                # Only send an expiry that differs from the node's; the service
                # falls back to the common expiry when the key is absent.
                if leg_expiry:
                    prepared["expiry_date"] = leg_expiry
                # Send exactly one strike selector so the service's branch is
                # unambiguous rather than relying on precedence.
                if prepared.get("strike") is None:
                    prepared.pop("strike", None)
                else:
                    prepared.pop("offset", None)
                legs.append(prepared)
        else:
            # Generate legs from predefined strategy type
            # A generated strategy shares one price type across its legs. Its
            # legs have no individual trigger price - the panel offers MARKET
            # and LIMIT only - so an SL type here has no way to carry the
            # trigger the broker requires. Say that, rather than sending a
            # zero trigger or rejecting it as a missing price.
            if multi_price_type in ("SL", "SL-M"):
                message = (
                    f"{multi_price_type} is not available for a generated "
                    f"{strategy_type} strategy: its legs carry no trigger price. "
                    "Use MARKET or LIMIT, or build the legs individually as custom "
                    "legs where each can set its own trigger price."
                )
                self.log(f"Options multi-order failed: {message}", "error")
                return {"status": "error", "message": message}
            invalid = self._invalid_price_reason(multi_price_type, multi_price, 0.0)
            if invalid:
                error_result = {"status": "error", "message": invalid}
                self.log(f"Options multi-order failed: {invalid}", "error")
                return error_result
            legs = self._generate_strategy_legs(
                strategy_type,
                action,
                total_quantity,
                product,
                strangle_width,
                price_type=multi_price_type,
                price=multi_price,
            )

        if not legs:
            error_result = {
                "status": "error",
                "message": f"No legs generated for strategy: {strategy_type}",
            }
            self.log(f"Options multi-order failed: {error_result['message']}", "error")
            return error_result

        self.log(f"Placing options multi-order: {underlying} {strategy_type} with {len(legs)} legs")
        for i, leg in enumerate(legs):
            # A manually built leg carries a strike instead of an offset, and
            # may carry its own expiry.
            selector = (
                f"{leg['strike']:g}" if leg.get("strike") is not None else leg.get("offset")
            )
            expiry_note = f" {leg['expiry_date']}" if leg.get("expiry_date") else ""
            self.log(
                f"  Leg {i + 1}: {selector}{expiry_note} {leg['option_type']} "
                f"{leg['action']} qty={leg['quantity']}"
            )

        result = self.client.options_multi_order(
            underlying=underlying,
            exchange=underlying_exchange,
            expiry_date=expiry_date,
            legs=legs,
            strategy=self.strategy_tag(node_data),
        )
        self.log(
            f"Options multi-order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def _generate_strategy_legs(
        self,
        strategy_type: str,
        action: str,
        quantity: int,
        product: str,
        strangle_width: str = "OTM2",
        price_type: str = "MARKET",
        price: float = 0.0,
    ) -> list[dict]:
        """Generate legs for predefined option strategies.

        `price_type` is honored rather than hardcoded: silently turning a
        documented LIMIT instruction into a MARKET order is the one outcome a
        trader can never recover from.
        """
        legs = []

        # Common leg template
        def make_leg(offset: str, option_type: str, leg_action: str) -> dict:
            return {
                "offset": offset,
                "option_type": option_type,
                "action": leg_action,
                "quantity": quantity,
                "pricetype": price_type,
                "product": product,
                "price": price,
                "splitsize": 0,
            }

        if strategy_type == "straddle":
            # Straddle: ATM CE + ATM PE (same action for both)
            legs.append(make_leg("ATM", "CE", action))
            legs.append(make_leg("ATM", "PE", action))

        elif strategy_type == "strangle":
            # Strangle: OTM CE + OTM PE (same action for both)
            # Use configurable width, default OTM2
            legs.append(make_leg(strangle_width, "CE", action))
            legs.append(make_leg(strangle_width, "PE", action))

        elif strategy_type == "iron_condor":
            # Iron Condor: 4 legs - sell near strikes, buy far strikes
            # Sell OTM2 CE, Buy OTM4 CE, Sell OTM2 PE, Buy OTM4 PE
            legs.append(make_leg("OTM2", "CE", "SELL"))
            legs.append(make_leg("OTM4", "CE", "BUY"))
            legs.append(make_leg("OTM2", "PE", "SELL"))
            legs.append(make_leg("OTM4", "PE", "BUY"))

        elif strategy_type == "bull_call_spread":
            # Bull Call Spread: Buy lower strike CE, Sell higher strike CE
            legs.append(make_leg("ATM", "CE", "BUY"))
            legs.append(make_leg("OTM2", "CE", "SELL"))

        elif strategy_type == "bear_put_spread":
            # Bear Put Spread: Buy higher strike PE, Sell lower strike PE
            legs.append(make_leg("ATM", "PE", "BUY"))
            legs.append(make_leg("OTM2", "PE", "SELL"))

        elif strategy_type == "custom":
            # Custom strategy requires legs to be provided
            self.log("Custom strategy selected but no legs provided", "warning")

        else:
            self.log(f"Unknown strategy type: {strategy_type}", "warning")

        return legs

    def _resolve_expiry_date(self, symbol: str, exchange: str, expiry_type: str) -> str | None:
        """The date a relative expiry type resolves to, in DDMMMYY.

        The selection rule itself lives in flow_node_contracts.select_expiry so
        the editor's expiry picker resolves it identically -- the panel shows
        the author which date a leg will actually use, and a second copy of the
        rule here would let that promise drift out of date.
        """
        try:
            response = self.client.get_expiry(
                symbol=symbol, exchange=exchange, instrumenttype="options"
            )
            if response.get("status") != "success":
                self.log(f"Failed to fetch expiry: {response}", "error")
                return None

            expiry_list = response.get("data", [])
            if not expiry_list:
                self.log(f"No expiry dates found for {symbol} on {exchange}", "error")
                return None

            selected = select_expiry(expiry_list, expiry_type)
            if not selected:
                self.log(
                    f"No expiry matches {expiry_type} for {symbol} on {exchange} "
                    f"among {len(expiry_list)} listed contract(s)",
                    "error",
                )
            return selected
        except Exception as e:
            self.log(f"Error resolving expiry: {e}", "error")
            return None

    def _format_expiry_for_api(self, expiry_str: str) -> str:
        """Format expiry date for API (e.g., '10-JUL-25' -> '10JUL25')"""
        if not expiry_str:
            return ""
        return expiry_str.replace("-", "").upper()

    def _supplied(self, node_data: dict, *keys: str) -> str | None:
        """First key the author actually filled in, interpolated. None if none."""
        for key in keys:
            if key not in node_data:
                continue
            text = self.context.interpolate(str(node_data.get(key) or "")).strip()
            if text:
                return text
        return None

    def execute_modify_order(self, node_data: dict) -> dict:
        """Execute Modify Order node.

        Every attribute except the ones being changed is read back from the live
        order. The editor only collects order id, new price and new quantity, so
        the rest used to come from hardcoded defaults -- action "BUY", product
        "MIS", price type "LIMIT", quantity 1 -- and those are sent to the broker
        verbatim. Brokers that carry them on a modify (Kotak, MStock, Pocketful,
        Tradejini, Definedge send action; Angel and Compositedge send product)
        would flip a live SELL to BUY or an NRML position to MIS, and a 500-lot
        order silently became 1 lot on brokers that accept the field without
        validating it. Resolving from the order book means an unspecified field
        keeps its current value, which is what "modify" means.
        """
        order_id = self.get_str(node_data, "orderId", "")
        if not order_id:
            message = "orderId is required to modify an order"
            self.log(f"Modify order aborted: {message}", "error")
            return {"status": "error", "message": message}

        existing = self.client.get_order_status(order_id)
        if existing.get("status") != "success" or not existing.get("data"):
            message = (
                f"Could not read order {order_id} to modify it: "
                f"{existing.get('message') or existing.get('error') or 'order not found'}"
            )
            self.log(f"Modify order aborted: {message}", "error")
            return {"status": "error", "message": message}

        live = existing["data"]

        # Identity of the order: never guessed. An explicit node value still
        # wins, so an imported workflow that set these on purpose keeps working.
        symbol = self._supplied(node_data, "symbol") or str(live.get("symbol", ""))
        exchange = self._supplied(node_data, "exchange") or str(live.get("exchange", ""))
        action = (self._supplied(node_data, "action") or str(live.get("action", ""))).upper()
        product = self._supplied(node_data, "product") or str(live.get("product", ""))
        price_type = (
            self._supplied(node_data, "priceType", "pricetype") or str(live.get("pricetype", ""))
        ).upper()

        missing = [
            name
            for name, value in (
                ("symbol", symbol),
                ("exchange", exchange),
                ("action", action),
                ("product", product),
                ("priceType", price_type),
            )
            if not value
        ]
        if missing:
            message = (
                f"Order {order_id} did not report {', '.join(missing)}; "
                "refusing to modify it with a guessed value"
            )
            self.log(f"Modify order aborted: {message}", "error")
            return {"status": "error", "message": message}

        # The three fields the node exists to change. Unspecified means unchanged,
        # so each falls back to the live order rather than to a literal default.
        quantity_text = self._supplied(node_data, "newQuantity", "quantity")
        price_text = self._supplied(node_data, "newPrice", "price")
        trigger_text = self._supplied(node_data, "newTriggerPrice", "triggerPrice")

        try:
            quantity = (
                int(float(quantity_text))
                if quantity_text
                else int(float(live.get("quantity", 0) or 0))
            )
            price = float(price_text) if price_text else float(live.get("price", 0) or 0)
            trigger_price = (
                float(trigger_text) if trigger_text else float(live.get("trigger_price", 0) or 0)
            )
        except (TypeError, ValueError) as e:
            message = f"Modify order got a non-numeric price or quantity: {e}"
            self.log(f"Modify order aborted: {message}", "error")
            return {"status": "error", "message": message}

        if quantity <= 0:
            message = f"Modify order needs a positive quantity, got {quantity}"
            self.log(f"Modify order aborted: {message}", "error")
            return {"status": "error", "message": message}

        self.log(
            f"Modifying order: {order_id} - {symbol} {action} qty={quantity} "
            f"price={price} trigger={trigger_price}"
        )
        result = self.client.modify_order(
            order_id=order_id,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            price_type=price_type,
            product_type=product,
            price=price,
            trigger_price=trigger_price,
        )
        self.log(
            f"Modify order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_cancel_order(self, node_data: dict) -> dict:
        """Execute Cancel Order node"""
        order_id = self.context.interpolate(str(node_data.get("orderId", "")))
        self.log(f"Cancelling order: {order_id}")
        result = self.client.cancel_order(order_id=order_id)
        self.log(
            f"Cancel result: {result}", "info" if result.get("status") == "success" else "error"
        )
        return result

    def execute_cancel_all_orders(self, node_data: dict) -> dict:
        """Execute Cancel All Orders node"""
        self.log("Cancelling all orders")
        result = self.client.cancel_all_orders()
        self.log(
            f"Cancel all result: {result}", "info" if result.get("status") == "success" else "error"
        )
        # Every other action node stores its result. Without this an
        # outputVariable set on this node stayed undefined, and the downstream
        # {{...}} that read it resolved to its own literal text.
        self.store_output(node_data, result)
        return result

    def execute_close_positions(self, node_data: dict) -> dict:
        """Execute Close Positions node - squares off positions.

        Honours the symbol/exchange/product filter the node advertises. The
        filter fields were read by nothing: whatever the user set, the executor
        called the unconditional square-off service. Because the node ships with
        exchange NSE and product MIS pre-filled, its canvas badge always claimed
        a scoped close, so a node that looked like "square off NSE intraday"
        liquidated MCX and NFO positions and overnight NRML/CNC holdings too.
        With no symbol set the behaviour is unchanged: close everything.
        """
        symbol = self._supplied(node_data, "symbol")
        if not symbol:
            self.log("Closing all positions")
            result = self.client.close_all_positions()
            self.log(
                f"Close all positions result: {result}",
                "info" if result.get("status") == "success" else "error",
            )
            self.store_output(node_data, result)
            return result

        exchange = self._supplied(node_data, "exchange") or "NSE"
        product = self._supplied(node_data, "product") or default_product_for_exchange(exchange)
        self.log(f"Closing position: {symbol}@{exchange} ({product})")
        result = self.client.close_position(
            symbol=symbol,
            exchange=exchange,
            product_type=product,
            strategy=self.strategy_tag(node_data),
        )
        self.log(
            f"Close position result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_basket_order(self, node_data: dict) -> dict:
        """Execute Basket Order node - places multiple orders in batch"""
        orders_raw = node_data.get("orders", "")
        if isinstance(orders_raw, str):
            orders_raw = self.context.resolve_raw(orders_raw)
        basket_name = self.get_str(node_data, "basketName", "flow_basket")

        def resolve(value: Any, field: str) -> Any:
            if isinstance(value, str):
                value = self.context.resolve_raw(value)
            if isinstance(value, str) and _UNRESOLVED_PATTERN.search(value):
                raise ValueError(f"{field} has unresolved value {value!r}")
            return value

        def common_value(key: str, default: Any) -> Any:
            if key not in node_data:
                return default
            return resolve(node_data[key], key)

        def number(value: Any, field: str) -> float:
            value = resolve(value, field)
            if isinstance(value, bool):
                raise ValueError(f"{field} must be numeric, got boolean {value!r}")
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"{field} must not be blank")
            try:
                numeric = float(value)
            except (OverflowError, TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be numeric, got {value!r}") from exc
            if not math.isfinite(numeric):
                raise ValueError(f"{field} must be finite, got {value!r}")
            return numeric

        def required_text(value: Any, field: str) -> str:
            value = resolve(value, field)
            if value is None:
                raise ValueError(f"{field} is required")
            text = str(value).strip()
            if not text:
                raise ValueError(f"{field} is required")
            return text

        def basket_error(index: int, detail: str) -> dict:
            message = f"Basket order row {index}: {detail}"
            self.log(f"Basket order failed: {message}", "error")
            return {"status": "error", "message": message}

        try:
            # One basket can mix segments, so a node that names no product lets
            # every row fall back to its own exchange's default -- NSE rows MIS,
            # NFO rows NRML -- instead of one blanket choice. A product that is
            # present but blank stays an error, as before.
            unset = object()
            common_product_raw = common_value("product", unset)
            common_product = (
                ""
                if common_product_raw is unset
                else required_text(common_product_raw, "product").upper()
            )
            common_price_type = required_text(
                common_value("priceType", "MARKET"), "priceType"
            ).upper()
            if common_product and common_product not in VALID_PRODUCT_TYPES:
                raise ValueError(f"invalid product {common_product!r}")
            if common_price_type not in VALID_PRICE_TYPES:
                raise ValueError(f"invalid pricetype {common_price_type!r}")
            common_price = number(common_value("price", 0.0), "price")
            common_trigger_price = number(common_value("triggerPrice", 0.0), "triggerPrice")
        except ValueError as exc:
            return basket_error(1, str(exc))

        raw_rows: list[tuple[int, dict, bool]] = []
        if isinstance(orders_raw, str):
            # Parse orders from CSV-like format: SYMBOL,EXCHANGE,ACTION,QTY per line
            for index, line in enumerate(orders_raw.strip().split("\n"), start=1):
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 4:
                    return basket_error(index, "expected SYMBOL,EXCHANGE,ACTION,QTY")
                raw_rows.append(
                    (
                        index,
                        {
                            "symbol": parts[0],
                            "exchange": parts[1],
                            "action": parts[2],
                            "quantity": parts[3],
                        },
                        True,
                    )
                )
        elif isinstance(orders_raw, list):
            for index, order in enumerate(orders_raw, start=1):
                if not isinstance(order, dict):
                    return basket_error(index, "must be an order object")
                raw_rows.append((index, order, False))

        if not raw_rows:
            error_result = {"status": "error", "message": "No valid orders to place"}
            self.log("Basket order failed: No valid orders", "error")
            return error_result

        orders = []
        for index, raw_order, csv_row in raw_rows:
            def row_value(
                key: str,
                default: Any,
                *aliases: str,
                is_csv_row: bool = csv_row,
                source_order: dict = raw_order,
            ) -> Any:
                if is_csv_row:
                    return default
                for candidate in (key, *aliases):
                    if candidate in source_order:
                        return resolve(source_order[candidate], candidate)
                return default

            try:
                symbol = required_text(raw_order.get("symbol"), "symbol")
                exchange = required_text(raw_order.get("exchange"), "exchange").upper()
                action = required_text(raw_order.get("action"), "action").upper()
                quantity_value = resolve(raw_order.get("quantity"), "quantity")
                quantity = int(number(quantity_value, "quantity"))
                if quantity <= 0:
                    raise ValueError(f"quantity must be positive, got {quantity}")

                product = required_text(
                    row_value("product", common_product or default_product_for_exchange(exchange)),
                    "product",
                ).upper()
                price_type = required_text(
                    row_value("pricetype", common_price_type, "priceType"), "pricetype"
                ).upper()
                if exchange not in VALID_EXCHANGES:
                    raise ValueError(f"invalid exchange {exchange!r}")
                if action not in VALID_ACTIONS:
                    raise ValueError(f"invalid action {action!r}")
                if product not in VALID_PRODUCT_TYPES:
                    raise ValueError(f"invalid product {product!r}")
                if price_type not in VALID_PRICE_TYPES:
                    raise ValueError(f"invalid pricetype {price_type!r}")
                price = number(row_value("price", common_price), "price")
                trigger_price = number(
                    row_value("triggerprice", common_trigger_price, "triggerPrice"), "triggerprice"
                )
                invalid = self._invalid_price_reason(str(price_type), price, trigger_price)
                if invalid:
                    raise ValueError(invalid)
            except (ValueError, TypeError) as exc:
                return basket_error(index, str(exc))

            orders.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "action": action,
                    "quantity": quantity,
                    "product": product,
                    "pricetype": price_type,
                    "price": price,
                    "triggerprice": trigger_price,
                }
            )

        self.log(f"Placing basket order '{basket_name}' with {len(orders)} orders")
        for i, order in enumerate(orders):
            self.log(
                f"  Order {i + 1}: {order['symbol']} {order['exchange']} {order['action']} qty={order['quantity']}"
            )

        result = self.client.basket_order(orders=orders, strategy=basket_name)
        self.log(
            f"Basket order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_split_order(self, node_data: dict) -> dict:
        """Execute Split Order node"""
        try:
            order = self.resolve_standard_order(node_data, "Split order")
            values = RuntimeOrderResolver(self.context, node_data, "Split order")
            split_size = values.integer("splitSize", default=10, minimum=1)
        except ValueError as exc:
            return self.runtime_order_error("Split order", exc)

        self.log(
            f"Placing split order: {order['symbol']} qty={order['quantity']} split={split_size}"
        )
        result = self.client.split_order(
            symbol=order["symbol"],
            exchange=order["exchange"],
            action=order["action"],
            quantity=order["quantity"],
            split_size=split_size,
            price_type=order["price_type"],
            product_type=order["product"],
            price=order["price"],
            trigger_price=order["trigger_price"],
            strategy=self.strategy_tag(node_data),
        )
        self.log(
            f"Split order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    # === Data Nodes ===

    def execute_get_quote(self, node_data: dict) -> dict:
        """Execute Get Quote node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Getting quote for: {symbol}")
        result = self.client.get_quotes(symbol=symbol, exchange=exchange)
        self.log(f"Quote result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_get_depth(self, node_data: dict) -> dict:
        """Execute Get Depth node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Getting depth for: {symbol}")
        result = self.client.get_depth(symbol=symbol, exchange=exchange)
        self.log("Depth result received")
        self.store_output(node_data, result)
        return result

    def execute_get_order_status(self, node_data: dict) -> dict:
        """Execute Get Order Status node"""
        order_id = self.get_str(node_data, "orderId", "")
        self.log(f"Getting order status for: {order_id}")
        result = self.client.get_order_status(order_id=order_id)
        self.log(f"Order status result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_open_position(self, node_data: dict) -> dict:
        """Execute Open Position node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        product = self.get_str(node_data, "product", default_product_for_exchange(exchange))
        self.log(f"Getting open position for: {symbol}")
        result = self.client.get_open_position(
            symbol=symbol, exchange=exchange, product_type=product
        )
        self.log(f"Open position result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_history(self, node_data: dict) -> dict:
        """Execute History node.

        The requested range is capped to the most recent MAX_HISTORY_BARS bars
        for the chosen interval - a 10-year 1-minute range is ~900k rows and
        must never be requested from the broker or held in workflow context.
        """
        from services.indicator_service import clamp_history_range, trim_records

        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        interval = self.get_str(node_data, "interval", "5m")
        start_date = self.get_str(node_data, "startDate", "")
        end_date = self.get_str(node_data, "endDate", "")
        # The panel offers a "Days" control, which was previously ignored -
        # configuring 30 days sent empty dates and silently got whatever the
        # broker defaults to. An explicit range still wins when both are set.
        if not (start_date and end_date):
            days = self.get_int(node_data, "days", 0)
            if days > 0:
                end_dt = datetime.now()
                start_dt = end_dt - timedelta(days=days)
                start_date = start_dt.strftime("%Y-%m-%d")
                end_date = end_dt.strftime("%Y-%m-%d")
                self.log(f"History range from days={days}: {start_date} to {end_date}")
        if start_date and end_date:
            start_date, end_date = clamp_history_range(start_date, end_date, interval)
        self.log(f"Getting history for: {symbol} ({interval})")
        result = self.client.get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        if isinstance(result, dict) and result.get("data"):
            result = {**result, "data": trim_records(result["data"])}
        self.log("History data received")
        self.store_output(node_data, result)
        return result

    @staticmethod
    def _history_error(
        response: dict | None, symbol: str, interval: str, source: str
    ) -> str | None:
        """Return a caller-facing message when a history fetch failed.

        Not every broker supports every interval, and an unsupported one comes
        back as a broker error - which would otherwise surface downstream as a
        misleading "no historical data available for this symbol/date range".
        """
        response = response or {}
        if response.get("status") == "error" or response.get("error"):
            detail = response.get("message") or response.get("error") or "unknown error"
            hint = ""
            if source != "db":
                hint = (
                    f" If your broker does not support the '{interval}' interval, use the "
                    "Intervals node to list supported ones, or set Source to Historify DB "
                    "to resample it locally."
                )
            return f"History fetch failed for {symbol} ({interval}): {detail}.{hint}"
        return None

    def execute_strategy_pnl(self, node_data: dict) -> dict:
        """Execute Strategy P&L node - realized / unrealized / total for one
        strategy, so a workflow can exit on its own performance rather than
        the account's.

        `strategy` defaults to this workflow's name, which is also the tag its
        order nodes apply, so the common case needs no configuration.
        """
        from services.strategy_pnl_service import get_strategy_pnl

        strategy = self.get_str(node_data, "strategy", "") or self.default_strategy
        result = get_strategy_pnl(self.client, strategy=strategy)
        if result.get("status") == "error":
            self.log(f"Strategy P&L error: {result.get('message')}", "error")
            return result

        self.log(
            f"Strategy P&L [{strategy}]: realized={result.get('realized')} "
            f"unrealized={result.get('unrealized')} total={result.get('total')} "
            f"openQty={result.get('open_quantity')}"
        )
        if result.get("unpriced_legs"):
            self.log(
                f"{result['unpriced_legs']} open leg(s) had no live price and were "
                "excluded from unrealized P&L",
                "warning",
            )
        self.store_output(node_data, result)
        return result

    def execute_prior_period_ohlc(self, node_data: dict) -> dict:
        """Execute Prior Period OHLC node.

        Returns the last fully-closed hour/day/week/month candle for a
        symbol (e.g. PDH/PDL/PDC for `previous_day`) without requiring the
        workflow author to compute a relative date - Flow JSON has no date
        arithmetic (see docs/prompt/flow-import-format.md), so that math
        happens here in Python instead, over a rolling window that
        comfortably absorbs weekends/holidays.
        """
        from services.indicator_service import (
            fetch_history_cached,
            history_window,
            prior_period_ohlc,
            trim_records,
        )

        symbol = self.context.interpolate(self.get_str(node_data, "symbol"))
        exchange = self.get_str(node_data, "exchange", "NSE")
        period = self.get_str(node_data, "period", "previous_day")
        source = self.get_str(node_data, "source", "api")
        if not symbol:
            return {"status": "error", "message": "Symbol is required"}

        interval = "1h" if period == "previous_hour" else "D"
        lookback_days = (
            5
            if period == "previous_hour"
            else (60 if period == "previous_month" else 21 if period == "previous_week" else 10)
        )
        start_date, end_date = history_window(lookback_days=lookback_days, interval=interval)
        self.log(f"Fetching {period} OHLC for: {symbol} ({exchange})")
        result = fetch_history_cached(
            self.client, symbol, exchange, interval, start_date, end_date, source
        )
        history_error = self._history_error(result, symbol, interval, source)
        if history_error:
            self.log(history_error, "error")
            return {"status": "error", "message": history_error}
        records = trim_records((result or {}).get("data") or [])
        try:
            row = prior_period_ohlc(records, period)
        except ValueError as e:
            self.log(f"Prior period OHLC error: {e}", "error")
            return {"status": "error", "message": str(e)}

        output = {
            "status": "success",
            "symbol": symbol,
            "exchange": exchange,
            **row,
            "pdh": row.get("high"),
            "pdl": row.get("low"),
            "pdc": row.get("close"),
        }
        self.log(
            f"{period} OHLC for {symbol}: H={output['pdh']} L={output['pdl']} "
            f"C={output['pdc']} (bucket={output['date']})"
        )
        self.store_output(node_data, output)
        return output

    def execute_bar_offset(self, node_data: dict) -> dict:
        """Execute Bar Offset node - OHLCV of the Nth closed bar back.

        `offsetBars=0` is the most recent CLOSED bar (not the still-forming
        one), `1` is one bar before that, etc. Works at any interval the
        broker (or, with source="db", Historify) supports, so this alone
        covers "N bars back" / "N hours back" / "N days back" style
        lookback without a separate node per unit.
        """
        from services.indicator_service import (
            bar_at_offset,
            clamp_bars,
            fetch_history_cached,
            history_window,
            trim_records,
        )

        symbol = self.context.interpolate(self.get_str(node_data, "symbol"))
        exchange = self.get_str(node_data, "exchange", "NSE")
        interval = self.get_str(node_data, "interval", "D")
        source = self.get_str(node_data, "source", "api")
        offset_bars = clamp_bars(self.get_int(node_data, "offsetBars", 0) + 1, "offset bars") - 1
        if not symbol:
            return {"status": "error", "message": "Symbol is required"}

        lookback_bars = offset_bars + 5
        start_date, end_date = history_window(lookback_bars=lookback_bars, interval=interval)
        self.log(f"Fetching bar offset {offset_bars} for {symbol} ({interval})")
        result = fetch_history_cached(
            self.client, symbol, exchange, interval, start_date, end_date, source
        )
        history_error = self._history_error(result, symbol, interval, source)
        if history_error:
            self.log(history_error, "error")
            return {"status": "error", "message": history_error}
        records = trim_records((result or {}).get("data") or [])
        row = bar_at_offset(records, offset_bars, interval=interval)
        if row is None:
            return {
                "status": "error",
                "message": f"Not enough history to reach {offset_bars} bars back for {symbol}",
            }

        output = {
            "status": "success",
            "symbol": symbol,
            "exchange": exchange,
            "offsetBars": offset_bars,
            "timestamp": row.get("timestamp"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
        }
        self.log(f"Bar offset {offset_bars} for {symbol}: {output}")
        self.store_output(node_data, output)
        return output

    def execute_indicator(self, node_data: dict) -> dict:
        """Execute Indicator node - any openalgo.ta indicator over a symbol's
        history, or nested on top of another Indicator node's output series
        when `sourceSeries` is set.
        """
        from services.indicator_service import (
            compute_indicator,
            fetch_history_cached,
            history_window,
            trim_records,
        )

        indicator_name = self.get_str(node_data, "indicatorName", "sma")
        lookback_bars = self.get_int(node_data, "lookbackBars", 100)
        tail_bars = self.get_int(node_data, "tailBars", 5)
        offset_bars = self.get_int(node_data, "offsetBars", 0)
        source_field = self.get_str(node_data, "sourceField", "")
        # The contract is a JSON string, and the validator now refuses anything
        # else. A workflow saved before that check exists may still carry the
        # object form, which used to reach json.loads as "{'period': 14}" and
        # fail the run outright -- so an already-stored graph is normalised
        # rather than broken.
        params_value = node_data.get("params")
        if isinstance(params_value, dict):
            self.log(
                "Indicator params were stored as an object; normalising to the "
                "JSON string form. Re-save the node to store it correctly.",
                "warning",
            )
            params = params_value
        else:
            params_raw = self.get_str(node_data, "params", "{}")
            try:
                params = json.loads(params_raw) if params_raw.strip() else {}
            except (ValueError, TypeError):
                return {"status": "error", "message": f"Invalid params JSON: {params_raw}"}
        if not isinstance(params, dict):
            return {
                "status": "error",
                "message": f"params must resolve to a JSON object, got {type(params).__name__}",
            }

        source_series_raw = node_data.get("sourceSeries")
        if source_series_raw not in (None, ""):
            # Nested mode: compute over another indicator's own series output
            # (e.g. {{rsi1.series}}, a list of {value/out0: number} rows, or a
            # raw list of numbers) instead of fetching fresh history. This is
            # what lets a workflow author build SMA(RSI(14), 9)-style
            # composite indicators.
            #
            # Uses resolve_raw(), NOT interpolate()+json.loads(): interpolate
            # always stringifies via Python str() (single-quoted repr for a
            # list of dicts), which is not valid JSON and would silently fail
            # json.loads on every real nested reference. resolve_raw returns
            # the actual stored list object when the field is exactly one
            # {{...}} token.
            raw_list = (
                self.context.resolve_raw(str(source_series_raw))
                if isinstance(source_series_raw, str)
                else source_series_raw
            )
            if isinstance(raw_list, str):
                try:
                    raw_list = json.loads(raw_list)
                except (ValueError, TypeError):
                    self.log(f"sourceSeries did not resolve to an array: {raw_list!r}", "error")
                    return {
                        "status": "error",
                        "message": "sourceSeries did not resolve to a JSON array",
                    }
            if not isinstance(raw_list, list):
                self.log(f"sourceSeries must resolve to an array, got: {raw_list!r}", "error")
                return {"status": "error", "message": "sourceSeries must resolve to an array"}
            numeric_series = []
            for item in raw_list:
                if isinstance(item, dict):
                    # `value`/`out0` come from another Indicator node; `close`
                    # (or an explicit sourceField) lets a raw History array be
                    # fed in directly, e.g. sourceSeries={{h.data}}.
                    if source_field:
                        value = item.get(source_field)
                    else:
                        value = next(
                            (
                                item[k]
                                for k in ("value", "out0", "close")
                                if item.get(k) is not None
                            ),
                            None,
                        )
                else:
                    value = item
                if value is None:
                    continue
                try:
                    numeric_series.append(float(value))
                except (TypeError, ValueError):
                    # Keep bad node input contained: without this the
                    # ValueError escapes execute_indicator and aborts the
                    # whole workflow instead of failing just this node.
                    self.log(f"sourceSeries contains a non-numeric value: {value!r}", "error")
                    return {
                        "status": "error",
                        "message": f"sourceSeries contains a non-numeric value: {value!r}",
                    }
            self.log(
                f"Computing nested {indicator_name} over {len(numeric_series)} upstream values"
            )
            try:
                output = compute_indicator(
                    None,
                    indicator_name,
                    params=params,
                    tail_bars=tail_bars,
                    source_series=numeric_series,
                    offset_bars=offset_bars,
                )
            except ValueError as e:
                self.log(f"Indicator error: {e}", "error")
                return {"status": "error", "message": str(e)}
            self.log(f"{indicator_name} (nested) latest: {output.get('latest')}")
            self.store_output(node_data, output)
            return output

        symbol = self.context.interpolate(self.get_str(node_data, "symbol"))
        exchange = self.get_str(node_data, "exchange", "NSE")
        interval = self.get_str(node_data, "interval", "D")
        source = self.get_str(node_data, "source", "api")
        if not symbol:
            return {"status": "error", "message": "Symbol is required"}

        start_date, end_date = history_window(lookback_bars=lookback_bars, interval=interval)
        self.log(f"Computing {indicator_name} for {symbol} ({interval}, {lookback_bars} bars)")
        history = fetch_history_cached(
            self.client, symbol, exchange, interval, start_date, end_date, source
        )
        history_error = self._history_error(history, symbol, interval, source)
        if history_error:
            self.log(history_error, "error")
            return {"status": "error", "message": history_error}
        records = trim_records((history or {}).get("data") or [])
        try:
            output = compute_indicator(
                records,
                indicator_name,
                params=params,
                lookback_bars=lookback_bars,
                tail_bars=tail_bars,
                offset_bars=offset_bars,
            )
        except ValueError as e:
            self.log(f"Indicator error: {e}", "error")
            return {"status": "error", "message": str(e)}

        self.log(f"{indicator_name} latest: {output.get('latest')}")
        self.store_output(node_data, output)
        return output

    def execute_order_book(self, node_data: dict) -> dict:
        """Execute OrderBook node"""
        self.log("Fetching order book")
        result = self.client.orderbook()
        self.log("Order book received")
        self.store_output(node_data, result)
        return result

    def execute_trade_book(self, node_data: dict) -> dict:
        """Execute TradeBook node"""
        self.log("Fetching trade book")
        result = self.client.tradebook()
        self.log("Trade book received")
        self.store_output(node_data, result)
        return result

    def execute_position_book(self, node_data: dict) -> dict:
        """Execute PositionBook node"""
        self.log("Fetching position book")
        result = self.client.positionbook()
        self.log("Position book received")
        self.store_output(node_data, result)
        return result

    def execute_holdings(self, node_data: dict) -> dict:
        """Execute Holdings node"""
        self.log("Fetching holdings")
        result = self.client.holdings()
        self.log("Holdings received")
        self.store_output(node_data, result)
        return result

    def execute_funds(self, node_data: dict) -> dict:
        """Execute Funds node"""
        self.log("Fetching funds")
        result = self.client.funds()
        self.log("Funds received")
        self.store_output(node_data, result)
        return result

    # === Additional Data Nodes ===

    def execute_symbol(self, node_data: dict) -> dict:
        """Execute Symbol node - get symbol info (lotsize, tick_size, etc.)"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Getting symbol info for: {symbol} ({exchange})")
        result = self.client.symbol(symbol=symbol, exchange=exchange)
        self.log(f"Symbol result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_option_symbol(self, node_data: dict) -> dict:
        """Execute OptionSymbol node - resolve option symbol from underlying"""
        underlying = self.get_str(node_data, "underlying", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NSE_INDEX")
        expiry_date = self.get_str(node_data, "expiryDate", "")
        offset = self.get_str(node_data, "offset", "ATM")
        option_type = self.get_str(node_data, "optionType", "CE")
        self.log(f"Resolving option symbol: {underlying} {option_type} {offset}")
        result = self.client.optionsymbol(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            offset=offset,
            option_type=option_type,
        )
        self.log(f"Option symbol result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_expiry(self, node_data: dict) -> dict:
        """Execute Expiry node - get expiry dates for F&O"""
        symbol = self.get_str(node_data, "symbol", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NFO")
        instrumenttype = self.get_str(node_data, "instrumenttype", "options").lower()
        if instrumenttype not in ("options", "futures"):
            instrumenttype = "options"
        self.log(f"Getting {instrumenttype} expiry dates for: {symbol}")
        result = self.client.get_expiry(
            symbol=symbol, exchange=exchange, instrumenttype=instrumenttype
        )
        self.log(f"Expiry result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_intervals(self, node_data: dict) -> dict:
        """Execute Intervals node - get available intervals for historical data"""
        self.log("Getting available intervals")
        result = self.client.get_intervals()
        self.log(f"Intervals result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_multi_quotes(self, node_data: dict) -> dict:
        """Execute Multi Quotes node - get quotes for multiple symbols"""
        # Interpolated like every sibling field. Left raw, `symbols` sent the
        # literal "{{sym.symbol}}" to the symbol validator, which failed with a
        # "not found" naming the brace text.
        raw_symbols = self.get_str(node_data, "symbols", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        # Convert comma-separated string to list of dicts expected by service
        if isinstance(raw_symbols, str):
            symbol_list = [s.strip() for s in raw_symbols.split(",") if s.strip()]
        else:
            symbol_list = raw_symbols
        symbols = [{"symbol": s, "exchange": exchange} for s in symbol_list]
        self.log(f"Getting quotes for {len(symbols)} symbols")
        result = self.client.get_multi_quotes(symbols=symbols)
        self.log(f"Multi quotes result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_option_chain(self, node_data: dict) -> dict:
        """Execute OptionChain node - get option chain data"""
        underlying = self.get_str(node_data, "underlying", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NSE_INDEX")
        expiry_date = self.get_str(node_data, "expiryDate", "")
        strike_count = self.get_int(node_data, "strikeCount", 10)
        self.log(f"Fetching option chain for: {underlying} expiry={expiry_date}")
        result = self.client.optionchain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=strike_count,
        )
        self.log("Option chain result received")
        self.store_output(node_data, result)
        return result

    def execute_synthetic_future(self, node_data: dict) -> dict:
        """Execute SyntheticFuture node - calculate synthetic future price"""
        underlying = self.get_str(node_data, "underlying", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NSE_INDEX")
        expiry_date = self.get_str(node_data, "expiryDate", "")
        self.log(f"Calculating synthetic future for: {underlying}")
        result = self.client.syntheticfuture(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
        )
        self.log(f"Synthetic future result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_calendar(self, node_data: dict) -> dict:
        """Execute Calendar node - trading-day facts for a date.

        Answers "has a new day/week/month/quarter/year started" without any
        cross-run state, by asking whether today is the first trading day of
        that period. Correct where the obvious tests are not: the 1st of a
        month falling on a Sunday, or a week whose Monday is a holiday.
        """
        from datetime import date as _date

        from utils.trading_calendar import describe

        raw = self.get_str(node_data, "date", "")
        if raw:
            try:
                day = _date.fromisoformat(raw[:10])
            except ValueError:
                error_result = {
                    "status": "error",
                    "message": f"Calendar date must be YYYY-MM-DD, got {raw!r}",
                }
                self.log(f"Calendar failed: {error_result['message']}", "error")
                return error_result
        else:
            # Session date, not the server's calendar date: between midnight and
            # the 03:00 IST rollover those differ, and a strategy asking "is a
            # new day" means the trading day.
            day = _date.fromisoformat(self.context._session_date())

        info = describe(day)
        result = {"status": "success", **info}
        self.log(
            f"Calendar {info['date']} ({info['weekday']}): trading={info['is_trading_day']} "
            f"newWeek={info['is_new_week']} newMonth={info['is_new_month']} "
            f"newQuarter={info['is_new_quarter']}"
        )
        self.store_output(node_data, result)
        return result

    def execute_holidays(self, node_data: dict) -> dict:
        """Execute Holidays node - get market holidays for a year."""
        year = self.get_int(node_data, "year", 0)
        self.log(f"Fetching holidays for year: {year or 'current'}")
        result = self.client.holidays(year=year or None)
        self.log("Holidays result received")
        self.store_output(node_data, result)
        return result

    def execute_timings(self, node_data: dict) -> dict:
        """Execute Timings node - get market timings for a date."""
        date_str = self.get_str(node_data, "date", "") or datetime.now().strftime("%Y-%m-%d")
        self.log(f"Fetching market timings for date: {date_str}")
        result = self.client.timings(date_str=date_str)
        self.log(f"Timings result: {result}")
        self.store_output(node_data, result)
        return result

    def _parse_margin_positions(self, node_data: dict) -> list[dict] | None:
        """Read the panel's positionsJson basket, if present and usable."""
        raw_key = next(
            (
                key
                for key in ("positionsJson", "positions")
                if key in node_data and node_data[key] is not None
            ),
            None,
        )
        if raw_key is None:
            return None
        raw = node_data[raw_key]
        if isinstance(raw, str):
            raw = self.context.resolve_raw(raw)
        if isinstance(raw, str):
            if _UNRESOLVED_PATTERN.search(raw):
                raise ValueError(f"Margin positions has unresolved value {raw!r}.")
            raw = raw.strip()
            # A basket was configured, so an empty result means interpolation
            # dropped it - an unset {{variable}}, not a request to price the
            # single position instead.
            if not raw:
                raise ValueError(
                    "Margin positions is empty after variable interpolation; "
                    "check the {{variable}} references in the basket."
                )
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError) as exc:
                # Falling back to the single position here priced a *different*
                # estimate - and the panel never exposes those fields, so it
                # was an empty symbol - while only logging a warning.
                raise ValueError(
                    f"Margin positions is not valid JSON after variable "
                    f"interpolation: {exc}"
                ) from exc
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError("Margin positions must be a JSON array of position objects.")
        if not raw:
            raise ValueError("Margin positions is an empty basket; add at least one position.")
        if any(not isinstance(entry, dict) for entry in raw):
            # Dropping the bad entries would quietly price part of the basket
            # and report it as the whole estimate.
            raise ValueError(
                "Margin positions must all be objects; the basket contains a "
                "non-object entry."
            )

        normalized: list[dict[str, Any]] = []
        for index, position in enumerate(raw, start=1):
            values = RuntimeOrderResolver(self.context, position, f"Margin position {index}")
            try:
                symbol = values.text("symbol").upper()
                exchange = values.enum("exchange", VALID_EXCHANGES)
                action = values.enum("action", VALID_ACTIONS)
                quantity = values.integer("quantity", minimum=1)
                product = values.enum("product", VALID_PRODUCT_TYPES)
                price_type = values.enum("pricetype", VALID_PRICE_TYPES)
                price = values.number("price", default=0.0)
                trigger_price = values.number(
                    "trigger_price", default=0.0, aliases=("triggerPrice",)
                )
                invalid = self._invalid_price_reason(price_type, price, trigger_price)
                if invalid:
                    raise ValueError(invalid)
            except ValueError as exc:
                raise ValueError(f"Margin position {index}: {exc}") from exc

            def numeric_text(number: float) -> str:
                return str(int(number)) if number.is_integer() else str(number)

            resolved_position = dict(position)
            resolved_position.update(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "action": action,
                    "quantity": str(quantity),
                    "product": product,
                    "pricetype": price_type,
                }
            )
            if "price" in position:
                resolved_position["price"] = numeric_text(price)
            if "trigger_price" in position or "triggerPrice" in position:
                resolved_position.pop("triggerPrice", None)
                resolved_position["trigger_price"] = numeric_text(trigger_price)
            normalized.append(resolved_position)
        return normalized

    def execute_margin(self, node_data: dict) -> dict:
        """Execute Margin node - calculate margin requirements"""
        # The panel can supply a whole basket as positionsJson; a single
        # position is the fallback. Ignoring positionsJson silently priced only
        # the first leg of a multi-leg estimate.
        try:
            positions = self._parse_margin_positions(node_data)
        except ValueError as exc:
            error_result = {"status": "error", "message": str(exc)}
            self.log(f"Margin failed: {exc}", "error")
            return error_result
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        quantity = self.get_int(node_data, "quantity", 1)
        price = self.get_float(node_data, "price", 0)
        product_type = self.get_str(node_data, "product", default_product_for_exchange(exchange))
        action = self.get_str(node_data, "action", "BUY")
        price_type = self.get_str(node_data, "priceType", "MARKET")
        if positions:
            self.log(f"Calculating margin for a basket of {len(positions)} position(s)")
        elif not symbol:
            # No basket and no single position. Calling the broker with an empty
            # symbol returns a confusing broker-side error instead of naming the
            # thing the node is actually missing.
            message = "Margin node has no positions and no symbol to price."
            self.log(f"Margin failed: {message}", "error")
            return {"status": "error", "message": message}
        else:
            self.log(f"Calculating margin for: {symbol} ({exchange})")
        result = self.client.margin(
            symbol=symbol,
            exchange=exchange,
            quantity=quantity,
            price=price,
            product_type=product_type,
            action=action,
            price_type=price_type,
            positions=positions,
        )
        self.log(f"Margin result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_math_expression(self, node_data: dict) -> dict:
        """Execute Math Expression node - evaluate mathematical expressions

        Supports:
        - Basic operators: +, -, *, /, %, ** (power)
        - Parentheses for grouping
        - Variable interpolation: {{variableName}}
        - Numbers (integers and decimals)

        Example: ({{ltp}} * {{lotSize}}) + {{brokerage}}
        """
        expression = node_data.get("expression", "")
        output_var = node_data.get("outputVariable", "result")

        if not expression:
            self.log("No expression provided", "error")
            return {"status": "error", "message": "No expression provided"}

        self.log(f"Evaluating: {expression}")

        try:
            # Step 1: Interpolate variables
            interpolated = self.context.interpolate(expression)
            self.log(f"Interpolated: {interpolated}")

            # Step 2: Safely evaluate the expression
            result = self._safe_eval_math(interpolated)

            # Step 3: Store result in output variable
            self.context.set_variable(output_var, result)
            self.log(f"Result: {output_var} = {result}")

            return {
                "status": "success",
                "expression": expression,
                "interpolated": interpolated,
                "result": result,
                "outputVariable": output_var,
            }

        except Exception as e:
            self.log(f"Math expression failed: {e}", "error")
            return {"status": "error", "message": str(e)}

    def _safe_eval_math(self, expression: str) -> float:
        """Safely evaluate a mathematical expression

        Uses Python's ast module to parse and evaluate only safe math operations.
        Prevents arbitrary code execution.
        """
        import ast
        import math
        import operator as op

        # Supported operators
        operators = {
            ast.Add: op.add,
            ast.Sub: op.sub,
            ast.Mult: op.mul,
            ast.Div: op.truediv,
            ast.Mod: op.mod,
            ast.Pow: op.pow,
            ast.USub: op.neg,
            ast.UAdd: op.pos,
        }

        def _eval(node):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                    return node.value
                raise ValueError(f"Unsupported constant: {node.value}")
            elif isinstance(node, ast.Call):
                if not (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "floor"
                    and len(node.args) == 1
                    and not node.keywords
                ):
                    raise ValueError("Only floor(expression) is supported")
                return math.floor(_eval(node.args[0]))
            elif isinstance(node, ast.BinOp):
                left = _eval(node.left)
                right = _eval(node.right)
                op_type = type(node.op)
                if op_type not in operators:
                    raise ValueError(f"Unsupported operator: {op_type.__name__}")
                if op_type is ast.Pow:
                    if abs(right) > 100:
                        raise ValueError(f"Exponent too large: {right} (max 100)")
                return operators[op_type](left, right)
            elif isinstance(node, ast.UnaryOp):
                operand = _eval(node.operand)
                op_type = type(node.op)
                if op_type not in operators:
                    raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
                return operators[op_type](operand)
            elif isinstance(node, ast.Expression):
                return _eval(node.body)
            else:
                raise ValueError(f"Unsupported expression type: {type(node).__name__}")

        cleaned = expression.strip()
        if not cleaned:
            raise ValueError("Empty expression")

        try:
            tree = ast.parse(cleaned, mode="eval")
            return float(_eval(tree))
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax: {e}") from e

    # === Utility Nodes ===

    # Longest a delay node may block. Anything longer belongs in a schedule.
    DELAY_MAX_SECONDS = 300
    # Wait Until sleeps inside the per-workflow lock and inside the HTTP request
    # that triggered the run, exactly as Delay does, so it needs the same kind
    # of bound. It is looser because waiting a few minutes for a square-off is
    # the point of the node; a wait measured in hours is a schedule, and saying
    # so is more useful than pinning a worker until the afternoon and answering
    # `already_running` to every trigger in between.
    WAIT_UNTIL_MAX_SECONDS = 1800

    def execute_delay(self, node_data: dict) -> dict:
        """Execute Delay node"""
        delay_value = node_data.get("delayValue")
        delay_unit = node_data.get("delayUnit", "seconds")

        if delay_value is not None:
            delay_value = int(delay_value)
            if delay_unit == "minutes":
                delay_seconds = delay_value * 60
            elif delay_unit == "hours":
                delay_seconds = delay_value * 3600
            else:
                delay_seconds = delay_value
        else:
            delay_ms = int(node_data.get("delayMs", 1000))
            delay_seconds = delay_ms / 1000

        # Bounded. This sleeps inside the per-workflow lock and, for a webhook
        # trigger, inside the request that fired it -- so an unbounded "2 hours"
        # pinned a Flask worker and made every later trigger return
        # already_running for the duration.
        if delay_seconds > self.DELAY_MAX_SECONDS:
            self.log(
                f"Delay of {delay_seconds}s exceeds the {self.DELAY_MAX_SECONDS}s "
                "maximum; waiting the maximum instead.",
                "warning",
            )
            delay_seconds = self.DELAY_MAX_SECONDS

        self.log(f"Waiting for {delay_seconds} seconds")
        time_module.sleep(delay_seconds)
        return {"status": "success", "message": f"Waited {delay_seconds}s"}

    def execute_wait_until(self, node_data: dict) -> dict:
        """Execute Wait Until node"""
        target_time_str = node_data.get("targetTime", "09:30")
        target_hour, target_minute, target_second = parse_time_string(target_time_str, 9, 30)
        target_time = time(target_hour, target_minute, target_second)

        now = datetime.now().time()
        now_seconds = now.hour * 3600 + now.minute * 60 + now.second
        target_seconds = target_time.hour * 3600 + target_time.minute * 60 + target_time.second

        if now_seconds >= target_seconds:
            self.log(f"Target time {target_time_str} already passed")
            return {"status": "success", "waited": False}

        wait_seconds = target_seconds - now_seconds
        if wait_seconds > self.WAIT_UNTIL_MAX_SECONDS:
            message = (
                f"Wait Until {target_time_str} is {wait_seconds}s away, over the "
                f"{self.WAIT_UNTIL_MAX_SECONDS}s limit. The wait holds this workflow's "
                f"lock and the request that triggered it, so every trigger in between "
                f"is answered 'already running'. Use a schedule trigger at "
                f"{target_time_str} instead, or split the square-off into its own "
                f"workflow."
            )
            self.log(f"Wait Until aborted: {message}", "error")
            return {"status": "error", "message": message}

        self.log(f"Waiting until {target_time_str} (~{wait_seconds}s)")
        time_module.sleep(wait_seconds)
        return {"status": "success", "waited": True}

    def execute_log(self, node_data: dict) -> dict:
        """Execute Log node"""
        message = self.context.interpolate(node_data.get("message", ""))
        log_level = node_data.get("level", "info")
        self.log(f"[LOG] {message}", log_level)
        return {"status": "success", "message": message}

    @staticmethod
    def _walk_variable_json_path(value: Any, json_path: str) -> Any:
        """Traverse dotted dict keys and bracketed list indexes without eval."""
        if not isinstance(json_path, str):
            raise ValueError("jsonPath must be a string")

        path = json_path.strip()
        if not path:
            return value

        position = 0
        while position < len(path):
            if path[position] == "[":
                closing = path.find("]", position + 1)
                if closing < 0:
                    raise ValueError(f"Invalid jsonPath: {json_path}")
                index_text = path[position + 1 : closing]
                if not index_text.isdigit():
                    raise ValueError(f"Invalid jsonPath index: {index_text}")
                if not isinstance(value, (list, tuple)):
                    raise TypeError("jsonPath index requires a list or tuple")
                value = value[int(index_text)]
                position = closing + 1
                if position < len(path) and path[position] not in ".[":
                    raise ValueError(f"Invalid jsonPath: {json_path}")
                continue

            if position:
                if path[position] != ".":
                    raise ValueError(f"Invalid jsonPath: {json_path}")
                position += 1

            key_start = position
            while position < len(path) and path[position] not in ".[]":
                position += 1
            key = path[key_start:position]
            if not key:
                raise ValueError(f"Invalid jsonPath: {json_path}")
            if not isinstance(value, dict):
                raise TypeError("jsonPath key requires an object")
            value = value[key]

            if position < len(path) and path[position] == "]":
                raise ValueError(f"Invalid jsonPath: {json_path}")

        return value

    def _lookup_variable_source(self, source_variable: Any, json_path: Any = None) -> Any:
        """Return a raw source variable, distinguishing missing values from None."""
        if not isinstance(source_variable, str) or not source_variable.strip():
            raise ValueError("sourceVariable is required")

        source_name = source_variable.strip()
        if source_name not in self.context.variables:
            raise KeyError(f"Source variable not found: {source_name}")

        source = self.context.variables[source_name]
        if json_path is None or json_path == "":
            return source
        return self._walk_variable_json_path(source, json_path)

    def execute_variable(self, node_data: dict) -> dict:
        """Execute Variable node, storing a result only after it fully succeeds."""
        var_name = node_data.get("variableName") or node_data.get("name", "")
        operation = node_data.get("operation", "set")
        var_value = node_data.get("value", "")

        if isinstance(var_value, str):
            var_value = self.context.interpolate(var_value)

        try:
            if operation == "set":
                result = var_value
                if isinstance(result, str) and (result.startswith("{") or result.startswith("[")):
                    try:
                        result = json.loads(result)
                    except json.JSONDecodeError:
                        pass
            elif operation == "get":
                result = self._lookup_variable_source(
                    node_data.get("sourceVariable"), node_data.get("jsonPath")
                )
            elif operation in {"add", "subtract", "multiply", "divide"}:
                current = float(self.context.get_variable(var_name, 0))
                value = float(var_value)
                if operation == "add":
                    result = current + value
                elif operation == "subtract":
                    result = current - value
                elif operation == "multiply":
                    result = current * value
                else:
                    if value == 0:
                        raise ValueError("Cannot divide by zero")
                    result = current / value
            elif operation == "increment":
                result = float(self.context.get_variable(var_name, 0)) + 1
            elif operation == "decrement":
                result = float(self.context.get_variable(var_name, 0)) - 1
            elif operation == "parse_json":
                result = json.loads(var_value)
            elif operation == "stringify":
                result = json.dumps(self._lookup_variable_source(node_data.get("sourceVariable")))
            elif operation == "append":
                current = self.context.get_variable(var_name, "")
                result = f"{current}{var_value}" if var_name in self.context.variables else str(var_value)
            else:
                raise ValueError(f"Unknown variable operation: {operation}")
        except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            message = f"Variable operation {operation!r} failed: {exc}"
            self.log(message, "error")
            return {"status": "error", "message": message}

        self.context.set_variable(var_name, result)
        self.log(f"Set variable {var_name} = {result}")
        return {"status": "success", "variable": var_name, "value": result}

    def execute_whatsapp_alert(self, node_data: dict) -> dict:
        """Execute WhatsApp Alert node"""
        message = self.context.interpolate(node_data.get("message", ""))
        to = self.context.interpolate(node_data.get("to", "")) or None
        self.log(f"Sending WhatsApp alert to {to or 'self'}: {message}")
        result = self.client.whatsapp(message=message, to=to)
        self.log(
            f"WhatsApp result: {result}", "info" if result.get("status") == "success" else "error"
        )
        return result

    def execute_telegram_alert(self, node_data: dict) -> dict:
        """Execute Telegram Alert node"""
        message = self.context.interpolate(node_data.get("message", ""))
        self.log(f"Sending Telegram alert: {message}")
        result = self.client.telegram(message=message)
        self.log(
            f"Telegram result: {result}", "info" if result.get("status") == "success" else "error"
        )
        return result

    # The editor's timeout box is labelled "Timeout (ms)" and its own fallback is
    # 30000, while the executor passed the number straight to httpx as seconds --
    # so the UI minimum of 1000 meant a 1000-second timeout. Values are read as
    # milliseconds and capped, because this call blocks the workflow lock and a
    # Flask worker for its whole duration.
    HTTP_TIMEOUT_MAX_MS = 60_000
    HTTP_TIMEOUT_DEFAULT_MS = 30_000

    @staticmethod
    def _redact_url(url: str) -> str:
        """URL without credentials or query string, for logs.

        The full interpolated URL was written to the execution log, which is
        persisted verbatim and rendered in the UI -- so any API key or token in
        a query string was stored in the clear.
        """
        from urllib.parse import urlsplit, urlunsplit

        try:
            parts = urlsplit(url)
        except ValueError:
            return "<unparseable url>"
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        redacted = urlunsplit((parts.scheme, host, parts.path, "", ""))
        return f"{redacted}?<redacted>" if parts.query else redacted

    @classmethod
    def _check_http_destination(cls, url: str) -> str | None:
        """Reject destinations a workflow must not reach. None when allowed.

        The URL is interpolated from workflow variables, and a webhook trigger
        puts its caller's JSON body into that context -- so whoever can fire the
        webhook can steer this request. Without a check it reaches the loopback
        interface (this very Flask app, with its session cookies), private LAN
        hosts, and cloud metadata at 169.254.169.254, and the response body is
        stored in an output variable, so the read is not blind.
        """
        import socket
        from ipaddress import ip_address
        from urllib.parse import urlsplit

        try:
            parts = urlsplit(url)
        except ValueError:
            return "URL could not be parsed"

        if parts.scheme not in ("http", "https"):
            return f"scheme {parts.scheme or 'none'!r} is not allowed; use http or https"

        host = parts.hostname
        if not host:
            return "URL has no host"

        try:
            infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            return f"host {host!r} could not be resolved ({e})"

        for info in infos:
            address = ip_address(info[4][0])
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
                or address.is_unspecified
            ):
                return f"host {host!r} resolves to {address}, which is not a public address"
        return None

    def execute_http_request(self, node_data: dict) -> dict:
        """Execute HTTP Request node"""
        import httpx

        method = self.get_str(node_data, "method", "GET").upper()
        # Read raw and interpolate exactly once, below. `get_str` interpolates,
        # and the second pass that used to follow it expanded any `{{...}}` a
        # payload had substituted into the first: an author writing
        # `/report/{{webhook.path}}` let the caller send
        # `{{funds.data.availablecash}}` and read a workflow variable back out
        # through the outbound URL.
        url = node_data.get("url", "")
        if not isinstance(url, str):
            url = str(url)
        headers_raw = node_data.get("headers", {})
        body = node_data.get("body", "")

        timeout_ms = self.get_int(node_data, "timeout", self.HTTP_TIMEOUT_DEFAULT_MS)
        if timeout_ms <= 0:
            timeout_ms = self.HTTP_TIMEOUT_DEFAULT_MS
        timeout = min(timeout_ms, self.HTTP_TIMEOUT_MAX_MS) / 1000

        if not url:
            return {"status": "error", "message": "No URL specified"}

        # The editor writes this field as a JSON string; only a dict was ever
        # read, so every header a user typed was silently dropped and requests
        # meant to be authenticated went out bare.
        # Parsed before its values are interpolated, never after. Interpolating
        # the JSON text first let a substituted value carry a quote and become
        # structure: `x", "X-Injected": "yes` closed the string and added a
        # header the author never wrote, sent to their authenticated endpoint.
        # A payload holding a bare quote also broke the parse outright.
        headers = {}
        if isinstance(headers_raw, str):
            text = headers_raw.strip()
            if text:
                try:
                    headers_raw = json.loads(text)
                except json.JSONDecodeError as e:
                    message = f"headers is not valid JSON: {e}"
                    self.log(f"HTTP request aborted: {message}", "error")
                    return {"status": "error", "message": message}
            else:
                headers_raw = {}
        if isinstance(headers_raw, dict):
            for key, value in headers_raw.items():
                headers[str(key)] = self.context.interpolate(str(value))
        else:
            message = f"headers must be a JSON object, got {type(headers_raw).__name__}"
            self.log(f"HTTP request aborted: {message}", "error")
            return {"status": "error", "message": message}

        url = self.context.interpolate(url)
        if isinstance(body, str) and body:
            body = self.context.interpolate(body)

        rejection = self._check_http_destination(url)
        if rejection:
            message = f"refusing to send this request: {rejection}"
            self.log(f"HTTP request aborted: {message}", "error")
            return {"status": "error", "message": message}

        self.log(f"HTTP {method} {self._redact_url(url)}")

        # Its own client, not the shared broker pool: a slow or hostile endpoint
        # here must not consume a connection that order placement needs.
        # follow_redirects stays off so a redirect cannot escape the destination
        # check above.
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            try:
                if method == "GET":
                    response = client.get(url, headers=headers)
                elif method in ("POST", "PUT", "PATCH"):
                    send = getattr(client, method.lower())
                    try:
                        body_json = json.loads(body) if body else {}
                        response = send(url, json=body_json, headers=headers)
                    except json.JSONDecodeError:
                        response = send(url, content=body, headers=headers)
                elif method == "DELETE":
                    response = client.delete(url, headers=headers)
                else:
                    return {"status": "error", "message": f"Unsupported method: {method}"}

                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text

                result = {
                    "status": "success" if response.is_success else "error",
                    "statusCode": response.status_code,
                    "data": response_data,
                }
                self.store_output(node_data, result)
                return result

            except httpx.HTTPError as e:
                return {"status": "error", "message": str(e)}

    # === Condition Nodes ===

    def _evaluate_condition(self, value: float, operator: str, threshold: float) -> bool:
        """Evaluate a condition"""
        operators = {
            "gt": value > threshold,
            "gte": value >= threshold,
            "lt": value < threshold,
            "lte": value <= threshold,
            "eq": value == threshold,
            "neq": value != threshold,
        }
        return operators.get(operator, False)

    def execute_position_check(self, node_data: dict) -> dict:
        """Execute Position Check node.

        Honors the UI's `condition` field (exists, not_exists, quantity_above,
        quantity_below, pnl_above, pnl_below). Earlier this read `operator` /
        `threshold` directly, which the UI never writes, so every condition
        defaulted to `gt 0` regardless of the dropdown selection.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        product = self.get_str(node_data, "product", default_product_for_exchange(exchange))
        condition = self.get_str(node_data, "condition", "exists")
        threshold = self.get_float(node_data, "threshold", 0.0)

        if not symbol:
            # Fail closed. An empty symbol reads back a zero-quantity position,
            # which makes `not_exists` true and `exists` false -- so an
            # unconfigured node silently answered whatever its condition needed
            # to let the downstream order fire.
            message = "Position Check has no symbol set, so it cannot guard anything."
            self.log(message, "error")
            return {"status": "error", "condition": False, "message": message}

        self.log(f"Checking position for: {symbol}")
        result = self.client.get_open_position(
            symbol=symbol, exchange=exchange, product_type=product
)
        # A failed read is not an answer. The client returns its failure under
        # "error" with no "data", so reading straight through gave 0 and the
        # node reported success: a broker session that had expired made
        # "the position" evaluate on zeroes and route a branch on nothing.
        # `priceAlert` has always checked this; these did not.
        if result.get("status") != "success":
            message = result.get("error") or result.get("message") or "the position lookup failed"
            self.log(f"Position check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}
        quantity = int(result.get("quantity", 0) or 0)
        pnl = float(result.get("pnl", 0) or 0)

        if condition == "exists":
            condition_met = quantity != 0
            log_msg = f"Position check: qty={quantity} != 0 = {condition_met}"
        elif condition == "not_exists":
            condition_met = quantity == 0
            log_msg = f"Position check: qty={quantity} == 0 = {condition_met}"
        elif condition == "quantity_above":
            condition_met = quantity > threshold
            log_msg = f"Position check: qty={quantity} > {threshold} = {condition_met}"
        elif condition == "quantity_below":
            condition_met = quantity < threshold
            log_msg = f"Position check: qty={quantity} < {threshold} = {condition_met}"
        elif condition == "pnl_above":
            condition_met = pnl > threshold
            log_msg = f"Position check: pnl={pnl} > {threshold} = {condition_met}"
        elif condition == "pnl_below":
            condition_met = pnl < threshold
            log_msg = f"Position check: pnl={pnl} < {threshold} = {condition_met}"
        else:
            message = (
                f"condition {condition!r} is not one this node can evaluate "
                "(exists, not_exists, quantity_above, quantity_below, "
                "pnl_above, pnl_below)"
            )
            self.log(f"Position check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}

        self.log(log_msg)
        return {
            "status": "success",
            "condition": condition_met,
            "quantity": quantity,
            "pnl": pnl,
        }

    def execute_fund_check(self, node_data: dict) -> dict:
        """Execute Fund Check node.

        UI writes a single `minAvailable` field — semantics: "trigger True
        if available cash is at least this much". The previous version read
        `operator`/`threshold` (never written by the UI), so it always
        defaulted to `available > 0` and ignored `minAvailable`.
        """
        # A node saved before minAvailable existed carries the old
        # operator/threshold pair. Reading only minAvailable would silently
        # treat those as a minimum of zero, so the guard would pass on any
        # balance - the exact bypass this field was added to prevent.
        if "minAvailable" in node_data:
            min_available = self.get_float(node_data, "minAvailable", 0.0)
        elif "threshold" in node_data:
            # This node only expresses "at least". A legacy less-than means the
            # opposite, so treating its threshold as a minimum would invert the
            # guard - refuse instead of guessing.
            legacy_operator = str(node_data.get("operator") or "gt").strip().lower()
            if legacy_operator not in ("gt", "gte", "ge", ">", ">="):
                message = (
                    f"Fund Check has a legacy '{legacy_operator}' comparison, which this "
                    "node cannot express - it only supports a minimum. Open the node and "
                    "set Minimum Available."
                )
                self.log(message, "error")
                return {"status": "error", "message": message}
            min_available = self.get_float(node_data, "threshold", 0.0)
            self.log(
                f"Fund Check is using its legacy threshold of {min_available}. "
                "Re-save the node to store it as Minimum Available.",
                "warning",
            )
        else:
            # Fail closed. Defaulting to zero turned this into `available >= 0`,
            # which is true on any balance including a negative one, so the guard
            # silently let every downstream order through.
            message = (
                "Fund Check has no Minimum Available set, so it cannot guard "
                "anything. Open the node and set a minimum."
            )
            self.log(message, "error")
            return {"status": "error", "condition": False, "message": message}

        self.log("Checking funds")
        result = self.client.funds()
        # A failed read is not an answer. The client returns its failure under
        # "error" with no "data", so reading straight through gave 0 and the
        # node reported success: a broker session that had expired made
        # "the funds" evaluate on zeroes and route a branch on nothing.
        # `priceAlert` has always checked this; these did not.
        if result.get("status") != "success":
            message = result.get("error") or result.get("message") or "the funds lookup failed"
            self.log(f"Fund check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}
        data = result.get("data", {}) or {}
        available = float(data.get("availablecash", 0) or 0)
        condition_met = available >= min_available
        self.log(f"Fund check: available={available} >= {min_available} = {condition_met}")
        return {"status": "success", "condition": condition_met, "available": available}

    def execute_price_condition(self, node_data: dict) -> dict:
        """Execute Price Condition node.

        Honors the UI fields the panel actually writes: `field` (ltp / open /
        high / low / prev_close / change_percent), `operator` (>, <, ==, >=,
        <=, !=), and `value` (the threshold). The previous implementation
        read `threshold` (never written by the UI) and passed the symbol
        operators to a helper that only recognized word-keys, so all
        comparisons collapsed to False regardless of the configured price.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        field = self.get_str(node_data, "field", "ltp")
        operator = self.get_str(node_data, "operator", ">")
        if field not in self.PRICE_CONDITION_FIELDS:
            message = (
                f"field {field!r} is not one of "
                f"{', '.join(sorted(self.PRICE_CONDITION_FIELDS))}"
            )
            self.log(f"Price check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}

        # Same rule as varCondition: an operator the comparison cannot honour
        # used to fall through to a silent False, which does not mean "the
        # condition did not hold" -- it means the check never ran, and the graph
        # then took the false branch as though it had.
        if operator not in self.COMPARISON_OPERATORS:
            message = (
                f"operator {operator!r} is not one of "
                f"{', '.join(sorted(self.COMPARISON_OPERATORS))}"
            )
            self.log(f"Price check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}

        # Accept both `value` (current UI) and `threshold` (legacy) for back-compat.
        value = node_data.get("value", node_data.get("threshold", 0))
        try:
            threshold = float(
                self.context.interpolate(str(value)) if value not in (None, "") else 0.0
            )
        except (TypeError, ValueError):
            message = f"value did not resolve to a number: {value!r}"
            self.log(f"Price check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}

        self.log(f"Checking price for: {symbol}")
        result = self.client.get_quotes(symbol=symbol, exchange=exchange)
        # A failed read is not an answer. The client returns its failure under
        # "error" with no "data", so reading straight through gave 0 and the
        # node reported success: a broker session that had expired made
        # "the price" evaluate on zeroes and route a branch on nothing.
        # `priceAlert` has always checked this; these did not.
        if result.get("status") != "success":
            message = result.get("error") or result.get("message") or "the price lookup failed"
            self.log(f"Price check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}
        data = result.get("data", {}) or {}

        if field == "change_percent":
            ltp = float(data.get("ltp", 0) or 0)
            prev_close = float(data.get("prev_close", 0) or 0)
            field_value = ((ltp - prev_close) / prev_close * 100.0) if prev_close else 0.0
        else:
            field_value = float(data.get(field, 0) or 0)

        condition_met = self._compare(field_value, operator, threshold)
        self.log(f"Price check: {field}={field_value} {operator} {threshold} = {condition_met}")
        return {
            "status": "success",
            "condition": condition_met,
            "ltp": float(data.get("ltp", 0) or 0),
            "field": field,
            "field_value": field_value,
        }

    def execute_var_condition(self, node_data: dict) -> dict:
        """Execute Var Condition node - compare any two interpolated values.

        Unlike `priceCondition` (which always re-fetches a live quote field),
        this compares whatever the caller puts on either side after
        `{{...}}` interpolation - a workflow variable, an indicator output
        (e.g. `{{rsi.latest.value}}`), a previous-day level
        (`{{pdhpdl.pdh}}`), or a literal number. Fills the gap flagged in
        docs/prompt/flow-import-format.md 8.5 ("wait for a varCondition
        node").
        """
        # Never route a branch on a value the author did not configure. An
        # unresolvable operand was already refused, but an *empty* one slipped
        # through: `get_str` substitutes its default for a falsy field, so a
        # blank Left Value became "0" and compared as `0 > 30 = False` with a
        # success status - taking the else-path on nothing at all. The editor's
        # validator rejects empty operands before a run starts, but that guard
        # lives outside the node and does not cover every path in (imported
        # JSON, a hand-edited flow), so the node now defends itself.
        left, error = self._operand(node_data, "leftValue")
        if error:
            return error
        right, error = self._operand(node_data, "rightValue")
        if error:
            return error

        operator = self.get_str(node_data, "operator", ">")
        # An operator `_compare` does not recognise used to fall through to
        # False, which is indistinguishable from a condition that genuinely did
        # not hold: the flow would quietly take the else-path forever. The
        # dropdown cannot produce one, an imported workflow can.
        if operator not in self.COMPARISON_OPERATORS:
            message = (
                f"operator {operator!r} is not one of "
                f"{', '.join(sorted(self.COMPARISON_OPERATORS))}"
            )
            self.log(f"Var check aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}

        condition_met = self._compare(left, operator, right)
        self.log(f"Var check: {left} {operator} {right} = {condition_met}")
        return {
            "status": "success",
            "condition": condition_met,
            "left": left,
            "operator": operator,
            "right": right,
        }

    def _operand(self, node_data: dict, key: str) -> tuple[float | None, dict | None]:
        """Resolve one varCondition operand to a float.

        Returns `(value, None)` on success and `(None, error_result)` when the
        operand is empty, unresolved (`{{typo}}` survives interpolation as
        literal text) or otherwise not a number - the error result is the node
        result to return, so the condition takes NEITHER branch.
        """
        raw = node_data.get(key, "")
        # A literal 0 is falsy, so it cannot go through `get_str`'s default
        # substitution or it would be indistinguishable from an empty field.
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw), None

        text = self.context.interpolate(str(raw if raw is not None else "")).strip()
        if not text:
            message = f"{key} is empty"
        else:
            try:
                return float(text), None
            except (TypeError, ValueError):
                message = f"{key} did not resolve to a number: {text!r}"

        self.log(f"Var check aborted: {message}", "error")
        return None, {"status": "error", "condition": False, "message": message}

    # Quote fields priceCondition can read, matching the editor's dropdown and
    # the import reference. Anything else used to read 0.0 out of the quote dict
    # and compare that, so a typo produced a confident, wrong answer.
    PRICE_CONDITION_FIELDS = frozenset(
        {"ltp", "open", "high", "low", "prev_close", "change_percent"}
    )

    # Operator vocabularies `_compare` understands: the symbols the editor
    # writes, plus the word forms some legacy node configs still carry.
    COMPARISON_OPERATORS = frozenset(
        {">", "gt", "<", "lt", "==", "eq", "!=", "neq", ">=", "gte", "<=", "lte"}
    )

    @staticmethod
    def _compare(left: float, operator: str, right: float) -> bool:
        """Compare two numbers using either symbol operators (>, <, ==, !=,
        >=, <=) used by the UI or word operators (gt, lt, eq, neq, gte, lte)
        used by some legacy node configs. Unknown operator → False."""
        ops = {
            ">": left > right,
            "gt": left > right,
            "<": left < right,
            "lt": left < right,
            "==": left == right,
            "eq": left == right,
            "!=": left != right,
            "neq": left != right,
            ">=": left >= right,
            "gte": left >= right,
            "<=": left <= right,
            "lte": left <= right,
        }
        return ops.get(operator, False)

    def execute_time_window(self, node_data: dict) -> dict:
        """Execute Time Window node.

        Honors the `invertCondition` toggle from the UI ("Trigger outside
        window"). Without inversion: True when current time is inside
        [startTime, endTime]. With inversion: True when current time is
        outside that range.
        """
        start_time_str = node_data.get("startTime", "09:15")
        end_time_str = node_data.get("endTime", "15:30")
        invert = bool(node_data.get("invertCondition", False))

        now = datetime.now().time()
        start_h, start_m, _ = parse_time_string(start_time_str, 9, 15)
        end_h, end_m, _ = parse_time_string(end_time_str, 15, 30)
        start_time = time(start_h, start_m)
        end_time = time(end_h, end_m)

        # A window whose end is before its start crosses midnight, so the two
        # halves are tested separately. The single chained comparison made
        # 22:00-02:00 unsatisfiable: always False, and always True once the
        # "trigger outside window" toggle inverted it, turning an overnight
        # MCX or crypto guard into an always-on gate.
        if start_time <= end_time:
            in_window = start_time <= now <= end_time
        else:
            in_window = now >= start_time or now <= end_time
        condition_met = (not in_window) if invert else in_window
        self.log(
            f"Time window: {start_time_str}-{end_time_str}, in_window={in_window}, "
            f"invert={invert}, result={condition_met}"
        )
        return {"status": "success", "condition": condition_met}

    def execute_time_condition(self, node_data: dict) -> dict:
        """Execute Time Condition node"""
        target_time_str = node_data.get("targetTime", "09:30")
        operator = node_data.get("operator", ">=")
        # The editor writes conditionType (entry/exit/custom) as a role tag on
        # the node. It never changes the comparison, but echoing it into the log
        # line and the result payload is what makes a graph with several time
        # gates readable in the execution log — "which 15:15 check was that?".
        condition_type = node_data.get("conditionType", "entry")

        now = datetime.now().time()
        # Seconds are kept. Dropping them made "after 15:29:59" behave as
        # "after 15:29:00", a minute early, while waitUntil parsing the very
        # same string honoured them -- so two nodes given one time disagreed.
        target_hour, target_minute, target_second = parse_time_string(target_time_str, 9, 30)
        target_time = time(target_hour, target_minute, target_second)

        now_seconds = now.hour * 3600 + now.minute * 60 + now.second
        target_seconds = target_time.hour * 3600 + target_time.minute * 60 + target_time.second

        if operator == ">=":
            condition_met = now_seconds >= target_seconds
        elif operator == "<=":
            condition_met = now_seconds <= target_seconds
        elif operator == ">":
            condition_met = now_seconds > target_seconds
        elif operator == "<":
            condition_met = now_seconds < target_seconds
        elif operator == "==":
            # Deliberately minute-precision: a second-exact equality would only
            # hold if a poll landed on that exact second, so it would almost
            # never fire.
            condition_met = now.hour == target_time.hour and now.minute == target_time.minute
        else:
            message = f"operator {operator!r} is not one of >=, <=, >, <, =="
            self.log(f"Time condition aborted: {message}", "error")
            return {"status": "error", "condition": False, "message": message}

        self.log(
            f"Time condition ({condition_type}): {now.strftime('%H:%M')} "
            f"{operator} {target_time_str} = {condition_met}"
        )
        return {
            "status": "success",
            "condition": condition_met,
            "condition_type": condition_type,
            "current_time": now.strftime("%H:%M:%S"),
            "target_time": target_time_str,
            "operator": operator,
        }

    def execute_price_alert(self, node_data: dict) -> dict:
        """Execute Price Alert trigger node"""
        from services.flow_price_monitor_service import FlowPriceMonitor

        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        # The editor writes its own vocabulary ("above", "crosses_below") while
        # this branch chain only ever spoke the monitor's canonical one. An
        # unmapped name matched nothing, so condition_met stayed False and the
        # run took the No branch even when the level was clearly met
        # ("LTP=1304.8 above 1304.0 = False"), silently skipping the order
        # wired to Yes. Normalize through the monitor's own alias table.
        condition_type = FlowPriceMonitor.normalize_condition(
            self.get_str(node_data, "condition", "greater_than")
        )
        price = self.get_float(node_data, "price", 0)
        price_lower = self.get_float(node_data, "priceLower", 0)
        price_upper = self.get_float(node_data, "priceUpper", 0)

        if not symbol:
            return {"status": "error", "condition": False}

        # When the price monitor started this run it has already evaluated the
        # condition against the tick that fired it. Re-fetching a quote here
        # races that tick - the price can retreat between the alert and the
        # graph walk - and a stateless re-check can never confirm a crossing at
        # all. Trust the trigger and carry its price through.
        webhook = self.context.get_variable("webhook") or {}
        if isinstance(webhook, dict) and webhook.get("trigger_type") == "price_alert":
            ltp = float(webhook.get("trigger_price") or 0)
            self.log(f"Price alert fired by monitor: {symbol} LTP={ltp} {condition_type} {price}")
            self.store_output(node_data, {"ltp": ltp, "condition_met": True})
            return {"status": "success", "condition": True, "ltp": ltp}

        result = self.client.get_quotes(symbol=symbol, exchange=exchange)
        if result.get("status") != "success":
            return {"status": "error", "condition": False}

        data = result.get("data", {})
        ltp = float(data.get("ltp", 0) if data else 0)

        if condition_type in ("greater_than", "crossing_up"):
            # A crossing needs the previous tick, which a single graph walk does
            # not have. Fall back to the level test rather than to False, which
            # would be indistinguishable from "the level was not reached".
            condition_met = ltp > price
        elif condition_type in ("less_than", "crossing_down"):
            condition_met = ltp < price
        elif condition_type == "crossing":
            tolerance = price * 0.001
            condition_met = abs(ltp - price) <= tolerance
        elif condition_type in ("entering_channel", "inside_channel"):
            condition_met = price_lower <= ltp <= price_upper
        elif condition_type in ("exiting_channel", "outside_channel"):
            condition_met = ltp < price_lower or ltp > price_upper
        elif condition_type in (
            "moving_up",
            "moving_down",
            "moving_up_percent",
            "moving_down_percent",
        ):
            # These compare against the previous tick, which only the monitor
            # keeps. Outside a monitor-fired run there is nothing to compare to.
            self.log(
                f"Price alert condition {condition_type!r} needs the previous tick and can "
                "only be evaluated by the price monitor; wire this node as the trigger.",
                "error",
            )
            return {"status": "error", "condition": False, "ltp": ltp}
        else:
            # Never silently false: an unknown condition can never be true,
            # which reads exactly like an unmet level. Error takes no branch.
            self.log(
                f"Price alert has an unrecognized condition "
                f"{node_data.get('condition')!r}; it can never be true.",
                "error",
            )
            return {"status": "error", "condition": False, "ltp": ltp}

        self.log(f"Price alert: {symbol} LTP={ltp} {condition_type} {price} = {condition_met}")
        self.store_output(node_data, {"ltp": ltp, "condition_met": condition_met})
        return {"status": "success", "condition": condition_met, "ltp": ltp}

    # === Streaming Nodes (WebSocket with REST API fallback) ===

    def _get_websocket_data(
        self, symbol: str, exchange: str, mode: str, timeout: float = 5.0
    ) -> dict | None:
        """
        Get market data via WebSocket subscription using callback approach.

        Uses a callback to capture data with the correct mode, bypassing the
        shared cache which may contain data from other modes (e.g., LTP overwriting Depth).

        Args:
            symbol: Symbol to subscribe to
            exchange: Exchange code
            mode: Subscription mode ("LTP", "Quote", or "Depth")
            timeout: Maximum time to wait for data in seconds

        Returns:
            Market data dict or None if failed
        """
        import threading

        try:
            from database.auth_db import get_broker_name, verify_api_key
            from services.websocket_service import get_websocket_connection, subscribe_to_symbols

            # Get username from API key
            username = verify_api_key(self.client.api_key)
            if not username:
                self.log("WebSocket: Invalid API key", "warning")
                return None

            # Get broker name
            broker = get_broker_name(self.client.api_key) or "unknown"

            # Try to get WebSocket connection
            success, ws_client, error = get_websocket_connection(username)
            if not success:
                self.log(f"WebSocket connection failed: {error}", "warning")
                return None

            # Map mode string to numeric for comparison
            mode_to_num = {"LTP": 1, "Quote": 2, "Depth": 3}
            expected_mode_num = mode_to_num.get(mode, 2)

            # Thread-safe container for captured data
            captured_data = {"data": None}
            # Real, not green: on_market_data() sets this from the websocket
            # client's asyncio loop thread while this greenlet waits on it.
            # A green Event set from a real thread never wakes its waiter,
            # so the node sat out its whole timeout. See
            # utils/real_threading.
            data_event = _real_threading.Event()

            def on_market_data(data):
                """Callback to capture data with matching mode and symbol"""
                if captured_data["data"] is not None:
                    return  # Already captured

                data_symbol = data.get("symbol", "")
                data_exchange = data.get("exchange", "")
                data_mode = data.get("mode")

                # Check if this is the data we're looking for
                if (
                    data_symbol == symbol
                    and data_exchange == exchange
                    and data_mode == expected_mode_num
                ):
                    # For Depth mode, verify we have actual depth data (not just empty init message)
                    if mode == "Depth":
                        nested = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
                        # Check multiple possible structures:
                        # 1. Standard: bids/asks arrays
                        # 2. Fyers: depth.buy/depth.sell arrays
                        bids = data.get("bids") or nested.get("bids") or []
                        asks = data.get("asks") or nested.get("asks") or []
                        # Fyers format: depth: {buy: [], sell: []}
                        depth_obj = data.get("depth", {}) or nested.get("depth", {})
                        if isinstance(depth_obj, dict):
                            bids = bids or depth_obj.get("buy", [])
                            asks = asks or depth_obj.get("sell", [])
                        if not bids and not asks:
                            return  # Skip empty depth messages, wait for actual data

                    captured_data["data"] = data
                    data_event.set()

            # Register callback before subscribing
            ws_client.register_callback("market_data", on_market_data)

            try:
                # Subscribe to symbol
                symbols = [{"symbol": symbol, "exchange": exchange}]
                sub_success, sub_result, _ = subscribe_to_symbols(username, broker, symbols, mode)
                if sub_success:
                    record_workflow_subscription(
                        self.context.workflow_id, symbol, exchange, mode
                    )

                if not sub_success:
                    self.log(f"WebSocket subscribe failed: {sub_result.get('message')}", "warning")
                    return None

                # Wait for data with the correct mode (using event instead of polling)
                if _real_threading.wait_for(data_event, timeout):
                    return captured_data["data"]
                else:
                    return None  # Timeout

            finally:
                # Always unregister callback
                ws_client.unregister_callback("market_data", on_market_data)

        except Exception as e:
            self.log(f"WebSocket error: {str(e)}", "warning")
            return None

    def execute_subscribe_ltp(self, node_data: dict) -> dict:
        """Execute Subscribe LTP node - get real-time LTP via WebSocket

        Connects to OpenAlgo WebSocket server and subscribes to LTP updates.
        Falls back to REST API if WebSocket fails or times out.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        output_var = node_data.get("outputVariable", "ltp")

        if not symbol:
            self.log("Subscribe LTP: No symbol specified", "error")
            return {"status": "error", "message": "No symbol specified"}

        self.log(f"Subscribing to LTP stream: {symbol} ({exchange})")

        # Try WebSocket first
        ws_data = self._get_websocket_data(symbol, exchange, "LTP", timeout=5.0)

        if ws_data:
            # LTP may be nested under 'data' or at top level
            nested_data = ws_data.get("data", {}) if isinstance(ws_data.get("data"), dict) else {}
            ltp = (
                nested_data.get("ltp")
                if nested_data.get("ltp") is not None
                else ws_data.get("ltp", 0)
            )

            streaming_result = {
                "status": "success",
                "type": "ltp",
                "symbol": symbol,
                "exchange": exchange,
                "ltp": ltp,
                "source": "websocket",
            }
            self.log(f"LTP for {symbol}: {ltp} (via WebSocket)")

            # Store in context variable
            self.context.set_variable(output_var, ltp)
            self.store_output(node_data, streaming_result)
            return streaming_result

        # Fallback to REST API
        self.log(f"WebSocket timeout/failed, falling back to REST API for {symbol}")

        try:
            result = self.client.get_quotes(symbol=symbol, exchange=exchange)

            if result.get("status") == "success":
                data = result.get("data", {})
                ltp = data.get("ltp", 0) if data else 0

                streaming_result = {
                    "status": "success",
                    "type": "ltp",
                    "symbol": symbol,
                    "exchange": exchange,
                    "ltp": ltp,
                    "source": "rest_api",
                }
                self.log(f"LTP for {symbol}: {ltp} (via REST API)")

                # Store in context variable
                self.context.set_variable(output_var, ltp)
                self.store_output(node_data, streaming_result)
                return streaming_result
            else:
                error_msg = result.get("error", "Failed to get LTP")
                self.log(f"Subscribe LTP error: {error_msg}", "error")
                return {
                    "status": "error",
                    "type": "ltp",
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": error_msg,
                }

        except Exception as e:
            self.log(f"Subscribe LTP exception: {str(e)}", "error")
            return {
                "status": "error",
                "type": "ltp",
                "symbol": symbol,
                "exchange": exchange,
                "error": str(e),
            }

    def execute_subscribe_quote(self, node_data: dict) -> dict:
        """Execute Subscribe Quote node - get real-time quote via WebSocket

        Connects to OpenAlgo WebSocket and subscribes to quote updates (OHLC + volume).
        Falls back to REST API if WebSocket fails or times out.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        output_var = node_data.get("outputVariable", "quote")

        if not symbol:
            self.log("Subscribe Quote: No symbol specified", "error")
            return {"status": "error", "message": "No symbol specified"}

        self.log(f"Subscribing to Quote stream: {symbol} ({exchange})")

        # Try WebSocket first
        ws_data = self._get_websocket_data(symbol, exchange, "Quote", timeout=5.0)

        if ws_data:
            # Quote data may be nested under 'data' or at top level
            nested_data = ws_data.get("data", {}) if isinstance(ws_data.get("data"), dict) else {}

            # Extract from nested level first, fallback to top level
            quote_data = {
                "ltp": nested_data.get("ltp")
                if nested_data.get("ltp") is not None
                else ws_data.get("ltp", 0),
                "open": nested_data.get("open") or ws_data.get("open", 0),
                "high": nested_data.get("high") or ws_data.get("high", 0),
                "low": nested_data.get("low") or ws_data.get("low", 0),
                "close": nested_data.get("close")
                or nested_data.get("prev_close")
                or ws_data.get("close", ws_data.get("prev_close", 0)),
                "volume": nested_data.get("volume") or ws_data.get("volume", 0),
                "prev_close": nested_data.get("prev_close") or ws_data.get("prev_close", 0),
            }

            streaming_result = {
                "status": "success",
                "type": "quote",
                "symbol": symbol,
                "exchange": exchange,
                "data": quote_data,
                "source": "websocket",
            }
            self.log(f"Quote for {symbol}: LTP={quote_data.get('ltp')} (via WebSocket)")

            # Store in context variable
            self.context.set_variable(output_var, quote_data)
            self.store_output(node_data, streaming_result)
            return streaming_result

        # Fallback to REST API
        self.log(f"WebSocket timeout/failed, falling back to REST API for {symbol}")

        try:
            result = self.client.get_quotes(symbol=symbol, exchange=exchange)

            if result.get("status") == "success":
                data = result.get("data", {})

                quote_data = (
                    {
                        "ltp": data.get("ltp", 0),
                        "open": data.get("open", 0),
                        "high": data.get("high", 0),
                        "low": data.get("low", 0),
                        "close": data.get("close", data.get("prev_close", 0)),
                        "volume": data.get("volume", 0),
                        "prev_close": data.get("prev_close", 0),
                    }
                    if data
                    else {}
                )

                streaming_result = {
                    "status": "success",
                    "type": "quote",
                    "symbol": symbol,
                    "exchange": exchange,
                    "data": quote_data,
                    "source": "rest_api",
                }
                self.log(f"Quote for {symbol}: LTP={quote_data.get('ltp')} (via REST API)")

                # Store in context variable
                self.context.set_variable(output_var, quote_data)
                self.store_output(node_data, streaming_result)
                return streaming_result
            else:
                error_msg = result.get("error", "Failed to get quote")
                self.log(f"Subscribe Quote error: {error_msg}", "error")
                return {
                    "status": "error",
                    "type": "quote",
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": error_msg,
                }

        except Exception as e:
            self.log(f"Subscribe Quote exception: {str(e)}", "error")
            return {
                "status": "error",
                "type": "quote",
                "symbol": symbol,
                "exchange": exchange,
                "error": str(e),
            }

    def execute_subscribe_depth(self, node_data: dict) -> dict:
        """Execute Subscribe Depth node - get market depth via WebSocket

        Connects to OpenAlgo WebSocket and subscribes to depth updates (order book).
        Falls back to REST API if WebSocket fails or times out.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        output_var = node_data.get("outputVariable", "depth")

        if not symbol:
            self.log("Subscribe Depth: No symbol specified", "error")
            return {"status": "error", "message": "No symbol specified"}

        self.log(f"Subscribing to Depth stream: {symbol} ({exchange})")

        # Try WebSocket first (shorter timeout for depth as it may not stream outside market hours)
        ws_data = self._get_websocket_data(symbol, exchange, "Depth", timeout=3.0)

        if ws_data:
            # Depth data may be nested under 'data' or at top level
            # Handle multiple nesting levels: ws_data -> data -> (actual depth fields)
            nested_data = ws_data.get("data", {}) if isinstance(ws_data.get("data"), dict) else {}

            # Check for Fyers format: depth: {buy: [], sell: []}
            depth_obj = ws_data.get("depth", {}) or nested_data.get("depth", {})
            if isinstance(depth_obj, dict) and (depth_obj.get("buy") or depth_obj.get("sell")):
                # Fyers format - convert to standard bids/asks
                bids = depth_obj.get("buy", [])
                asks = depth_obj.get("sell", [])
                # Convert Fyers format (price/quantity) if needed
                if bids and isinstance(bids[0], dict) and "price" in bids[0]:
                    bids = [
                        {
                            "price": b.get("price", 0),
                            "quantity": b.get("quantity", b.get("volume", 0)),
                        }
                        for b in bids
                    ]
                if asks and isinstance(asks[0], dict) and "price" in asks[0]:
                    asks = [
                        {
                            "price": a.get("price", 0),
                            "quantity": a.get("quantity", a.get("volume", 0)),
                        }
                        for a in asks
                    ]
            else:
                # Standard format
                bids = nested_data.get("bids") or ws_data.get("bids", [])
                asks = nested_data.get("asks") or ws_data.get("asks", [])

            # Extract depth fields
            depth_data = {
                "bids": bids,
                "asks": asks,
                "totalbuyqty": nested_data.get("totalbuyqty") or ws_data.get("totalbuyqty", 0),
                "totalsellqty": nested_data.get("totalsellqty") or ws_data.get("totalsellqty", 0),
                "ltp": nested_data.get("ltp")
                if nested_data.get("ltp") is not None
                else ws_data.get("ltp", 0),
            }

            streaming_result = {
                "status": "success",
                "type": "depth",
                "symbol": symbol,
                "exchange": exchange,
                "data": depth_data,
                "source": "websocket",
            }
            # Log depth summary with top bid/ask prices
            bids_list = depth_data.get("bids", [])
            asks_list = depth_data.get("asks", [])
            top_bid = bids_list[0].get("price", 0) if bids_list else 0
            top_ask = asks_list[0].get("price", 0) if asks_list else 0
            self.log(
                f"Depth for {symbol}: Bid={top_bid}, Ask={top_ask} ({len(bids_list)} bids, {len(asks_list)} asks) via WebSocket"
            )

            # Store in context variable
            self.context.set_variable(output_var, depth_data)
            self.store_output(node_data, streaming_result)
            return streaming_result

        # Fallback to REST API
        self.log(f"WebSocket timeout/failed, falling back to REST API for {symbol}")

        try:
            result = self.client.get_depth(symbol=symbol, exchange=exchange)

            if result.get("status") == "success":
                data = result.get("data", {})

                depth_data = (
                    {
                        "bids": data.get("bids", []),
                        "asks": data.get("asks", []),
                        "totalbuyqty": data.get("totalbuyqty", 0),
                        "totalsellqty": data.get("totalsellqty", 0),
                        "ltp": data.get("ltp", 0),
                    }
                    if data
                    else {"bids": [], "asks": []}
                )

                streaming_result = {
                    "status": "success",
                    "type": "depth",
                    "symbol": symbol,
                    "exchange": exchange,
                    "data": depth_data,
                    "source": "rest_api",
                }
                # Log depth summary with top bid/ask prices
                bids_list = depth_data.get("bids", [])
                asks_list = depth_data.get("asks", [])
                top_bid = bids_list[0].get("price", 0) if bids_list else 0
                top_ask = asks_list[0].get("price", 0) if asks_list else 0
                self.log(
                    f"Depth for {symbol}: Bid={top_bid}, Ask={top_ask} ({len(bids_list)} bids, {len(asks_list)} asks) via REST API"
                )

                # Store in context variable
                self.context.set_variable(output_var, depth_data)
                self.store_output(node_data, streaming_result)
                return streaming_result
            else:
                error_msg = result.get("error", "Failed to get depth")
                self.log(f"Subscribe Depth error: {error_msg}", "error")
                return {
                    "status": "error",
                    "type": "depth",
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": error_msg,
                }

        except Exception as e:
            self.log(f"Subscribe Depth exception: {str(e)}", "error")
            return {
                "status": "error",
                "type": "depth",
                "symbol": symbol,
                "exchange": exchange,
                "error": str(e),
            }

    def execute_unsubscribe(self, node_data: dict) -> dict:
        """Execute Unsubscribe node - unsubscribe from WebSocket streams

        Unsubscribes from specified stream type (ltp/quote/depth/all).
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        stream_type = self.get_str(node_data, "streamType", "all")

        self.log(f"Unsubscribing from {stream_type} stream: {symbol or 'all'} ({exchange})")

        try:
            from database.auth_db import get_broker_name, verify_api_key
            from services.websocket_service import (
                get_websocket_connection,
                unsubscribe_all,
                unsubscribe_from_symbols,
            )

            # Get username from API key
            username = verify_api_key(self.client.api_key)
            if not username:
                self.log("Unsubscribe: Invalid API key", "warning")
                return {
                    "status": "success",
                    "type": "unsubscribe",
                    "message": "No active WebSocket connection",
                }

            # Get broker name
            broker = get_broker_name(self.client.api_key) or "unknown"

            # Check WebSocket connection
            success, ws_client, error = get_websocket_connection(username)
            if not success:
                return {
                    "status": "success",
                    "type": "unsubscribe",
                    "message": "No active WebSocket connection",
                }

            # Map stream_type to mode
            mode_map = {"ltp": "LTP", "quote": "Quote", "depth": "Depth"}

            # `unsubscribe_all` clears the process-wide client's entire
            # subscription set, which the Sandbox engine shares: it is what
            # feeds pending SL and LIMIT triggers. Reaching it because a
            # specific mode happened to have no symbol tore that down on a node
            # whose author had asked only for LTP. Only an explicit "all" gets
            # there now; an under-specified request is refused instead.
            if stream_type.lower() == "all":
                unsub_success, unsub_result, _ = unsubscribe_all(username, broker)
                self.log("Unsubscribed from all streams")
            elif not symbol:
                message = (
                    f"Unsubscribe is set to '{stream_type}' with no symbol. Name a "
                    f"symbol, or set Stream Type to 'all' if you really mean every "
                    f"subscription on this instance, including the Sandbox engine's."
                )
                self.log(f"Unsubscribe aborted: {message}", "error")
                return {"status": "error", "type": "unsubscribe", "message": message}
            else:
                # Unsubscribe from specific symbol/mode
                mode = mode_map.get(stream_type.lower(), "Quote")
                symbols = [{"symbol": symbol, "exchange": exchange}]
                unsub_success, unsub_result, _ = unsubscribe_from_symbols(
                    username, broker, symbols, mode
                )
                self.log(f"Unsubscribed from {stream_type} for {symbol}")

            # `unsub_success` was assigned by both branches and then never read,
            # so a rejected unsubscribe still returned success and a run that
            # had leaked its subscriptions was recorded as clean.
            if not unsub_success:
                message = (
                    unsub_result.get("message")
                    if isinstance(unsub_result, dict)
                    else str(unsub_result)
                ) or "unsubscribe was rejected"
                self.log(f"Unsubscribe failed: {message}", "error")
                return {"status": "error", "type": "unsubscribe", "message": message}

            return {
                "status": "success",
                "type": "unsubscribe",
                "symbol": symbol,
                "exchange": exchange,
                "stream_type": stream_type,
                "message": f"Unsubscribed from {stream_type} stream",
            }

        except Exception as e:
            self.log(f"Unsubscribe error: {str(e)}", "warning")
            return {
                "status": "success",
                "type": "unsubscribe",
                "symbol": symbol,
                "exchange": exchange,
                "stream_type": stream_type,
                "message": "Unsubscribe completed (with warnings)",
            }

    # === Logic Gates ===

    def execute_and_gate(self, node_data: dict, input_results: list[bool]) -> dict:
        """Execute AND Gate"""
        if not input_results:
            return {"status": "success", "condition": False}
        condition_met = all(input_results)
        self.log(f"AND Gate: {input_results} -> {condition_met}")
        return {"status": "success", "condition": condition_met}

    def execute_or_gate(self, node_data: dict, input_results: list[bool]) -> dict:
        """Execute OR Gate"""
        if not input_results:
            return {"status": "success", "condition": False}
        condition_met = any(input_results)
        self.log(f"OR Gate: {input_results} -> {condition_met}")
        return {"status": "success", "condition": condition_met}

    def execute_not_gate(self, node_data: dict, input_results: list[bool]) -> dict:
        """Execute NOT Gate"""
        input_value = input_results[0] if input_results else False
        condition_met = not input_value
        self.log(f"NOT Gate: {input_value} -> {condition_met}")
        return {"status": "success", "condition": condition_met}


def execute_node_chain(
    node_id: str,
    nodes: list,
    edge_map: dict[str, list[dict]],
    incoming_edge_map: dict[str, list[dict]],
    executor: NodeExecutor,
    context: WorkflowContext,
    visited_count: dict[str, int],
    depth: int = 0,
):
    """Execute a chain of nodes"""
    if depth > MAX_NODE_DEPTH:
        raise Exception(f"Maximum node depth ({MAX_NODE_DEPTH}) exceeded")

    total_visits = sum(visited_count.values())
    if total_visits >= MAX_NODE_VISITS:
        raise Exception(f"Maximum node visits ({MAX_NODE_VISITS}) exceeded")

    visited_count[node_id] = visited_count.get(node_id, 0) + 1

    node = next((n for n in nodes if n["id"] == node_id), None)
    if not node:
        return

    node_type = node.get("type")
    node_data = node.get("data", {})
    result = None

    # A condition reachable by more than one path evaluated once per path, and
    # each evaluation followed its branch again: a diamond where two upstream
    # nodes both lead to one condition placed two orders from a single trigger.
    # Gates already carried this guard; conditions did not, though they are
    # combinational in exactly the same way. The first traversal has already
    # followed the branch, so returning here is not a skipped step.
    if node_type in BRANCHING_NODE_TYPES and context.get_condition_result(node_id) is not None:
        return

    # An order node whose order-defining fields still contain {{...}} must not
    # reach the broker with those references replaced by field defaults.
    blocked_fields = (
        executor.unresolved_order_fields(node_data) if node_type in ORDER_NODE_TYPES else []
    )
    option_expiry_error = (
        executor.option_expiry_error(node_type, node_data)
        if node_type in OPTION_EXPIRY_NODE_TYPES
        else None
    )

    # Execute node based on type
    if blocked_fields:
        result = executor.unresolved_error(node_type, blocked_fields)
    elif option_expiry_error:
        result = option_expiry_error
    elif node_type == "start":
        executor.log("Workflow started")
    elif node_type == "placeOrder":
        result = executor.execute_place_order(node_data)
    elif node_type == "smartOrder":
        result = executor.execute_smart_order(node_data)
    elif node_type == "optionsOrder":
        result = executor.execute_options_order(node_data)
    elif node_type == "modifyOrder":
        result = executor.execute_modify_order(node_data)
    elif node_type == "optionsMultiOrder":
        result = executor.execute_options_multi_order(node_data)
    elif node_type == "cancelOrder":
        result = executor.execute_cancel_order(node_data)
    elif node_type == "cancelAllOrders":
        result = executor.execute_cancel_all_orders(node_data)
    elif node_type == "closePositions":
        result = executor.execute_close_positions(node_data)
    elif node_type == "basketOrder":
        result = executor.execute_basket_order(node_data)
    elif node_type == "splitOrder":
        result = executor.execute_split_order(node_data)
    elif node_type == "getQuote":
        result = executor.execute_get_quote(node_data)
    elif node_type == "getDepth":
        result = executor.execute_get_depth(node_data)
    elif node_type == "getOrderStatus":
        result = executor.execute_get_order_status(node_data)
    elif node_type == "openPosition":
        result = executor.execute_open_position(node_data)
    elif node_type == "history":
        result = executor.execute_history(node_data)
    elif node_type == "strategyPnl":
        result = executor.execute_strategy_pnl(node_data)
    elif node_type == "priorPeriodOhlc":
        result = executor.execute_prior_period_ohlc(node_data)
    elif node_type == "barOffset":
        result = executor.execute_bar_offset(node_data)
    elif node_type == "indicator":
        result = executor.execute_indicator(node_data)
    elif node_type == "symbol":
        result = executor.execute_symbol(node_data)
    elif node_type == "optionSymbol":
        result = executor.execute_option_symbol(node_data)
    elif node_type == "expiry":
        result = executor.execute_expiry(node_data)
    elif node_type == "intervals":
        result = executor.execute_intervals(node_data)
    elif node_type == "multiQuotes":
        result = executor.execute_multi_quotes(node_data)
    elif node_type == "optionChain":
        result = executor.execute_option_chain(node_data)
    elif node_type == "syntheticFuture":
        result = executor.execute_synthetic_future(node_data)
    elif node_type == "calendar":
        result = executor.execute_calendar(node_data)
    elif node_type == "holidays":
        result = executor.execute_holidays(node_data)
    elif node_type == "timings":
        result = executor.execute_timings(node_data)
    elif node_type == "orderBook":
        result = executor.execute_order_book(node_data)
    elif node_type == "tradeBook":
        result = executor.execute_trade_book(node_data)
    elif node_type == "positionBook":
        result = executor.execute_position_book(node_data)
    elif node_type == "holdings":
        result = executor.execute_holdings(node_data)
    elif node_type == "funds":
        result = executor.execute_funds(node_data)
    elif node_type == "margin":
        result = executor.execute_margin(node_data)
    elif node_type == "delay":
        result = executor.execute_delay(node_data)
    elif node_type == "waitUntil":
        result = executor.execute_wait_until(node_data)
    elif node_type == "log":
        result = executor.execute_log(node_data)
    elif node_type == "variable":
        result = executor.execute_variable(node_data)
    elif node_type == "mathExpression":
        result = executor.execute_math_expression(node_data)
    elif node_type == "group":
        # Group is just a container, pass through
        pass
    elif node_type == "telegramAlert":
        result = executor.execute_telegram_alert(node_data)
    elif node_type == "whatsappAlert":
        result = executor.execute_whatsapp_alert(node_data)
    elif node_type == "httpRequest":
        result = executor.execute_http_request(node_data)
    elif node_type == "positionCheck":
        result = executor.execute_position_check(node_data)
    elif node_type == "fundCheck":
        result = executor.execute_fund_check(node_data)
    elif node_type == "priceCondition":
        result = executor.execute_price_condition(node_data)
    elif node_type == "varCondition":
        result = executor.execute_var_condition(node_data)
    elif node_type == "timeWindow":
        result = executor.execute_time_window(node_data)
    elif node_type == "timeCondition":
        result = executor.execute_time_condition(node_data)
    elif node_type == "priceAlert":
        result = executor.execute_price_alert(node_data)
    elif node_type == "webhookTrigger":
        executor.log("Webhook trigger activated")
    elif node_type == "orderUpdateTrigger":
        executor.log("Order-update trigger activated")
    # Streaming Nodes
    elif node_type == "subscribeLtp":
        result = executor.execute_subscribe_ltp(node_data)
    elif node_type == "subscribeQuote":
        result = executor.execute_subscribe_quote(node_data)
    elif node_type == "subscribeDepth":
        result = executor.execute_subscribe_depth(node_data)
    elif node_type == "unsubscribe":
        result = executor.execute_unsubscribe(node_data)
    elif node_type in GATE_NODE_TYPES:
        # Gates must wait until every wired input has actually been evaluated.
        # The graph walk is depth-first, so the first input to finish would
        # otherwise reach the gate while the others are still unevaluated:
        # the gate fired on partial inputs ("A AND B" firing on A alone) AND
        # fired again for each remaining input, duplicating whatever is
        # downstream - two orders from one crossover. Skipping here is safe
        # because the later input's own traversal reaches this gate again,
        # by which point every source has a stored result.
        #
        # A gate is also combinational: exactly one result per run. It is
        # commonly reachable by several paths (one per input edge, plus a
        # pass-through from a shared parent), and each later arrival would
        # otherwise re-evaluate it and re-fire everything downstream.
        if context.get_condition_result(node_id) is not None:
            return
        incoming_edges = incoming_edge_map.get(node_id, [])
        input_results = []
        pending = 0
        for edge in incoming_edges:
            source_result = context.get_condition_result(edge.get("source"))
            if source_result is None:
                pending += 1
            else:
                input_results.append(source_result)
        if pending:
            executor.log(f"{node_type}: waiting for {pending} more input(s) before evaluating")
            return
        # `inputCount` is what the author configured and what the node renders
        # slots for; the wiring is what they actually connected. Firing on the
        # wires alone meant a deleted third edge silently downgraded
        # "A AND B AND in-window" to "A AND B", with the graph still showing
        # three slots and import validation raising nothing.
        declared = node_data.get("inputCount")
        if isinstance(declared, int) and declared > len(incoming_edges):
            message = (
                f"{node_type} is configured for {declared} inputs but only "
                f"{len(incoming_edges)} are wired. Wire the rest, or lower the "
                f"input count, rather than evaluating on part of the condition."
            )
            executor.log(message, "error")
            executor.errors.append({"node": node_id, "type": node_type, "message": message})
            return
        if node_type == "andGate":
            result = executor.execute_and_gate(node_data, input_results)
        elif node_type == "orGate":
            result = executor.execute_or_gate(node_data, input_results)
        else:
            result = executor.execute_not_gate(node_data, input_results)
    else:
        executor.log(f"Unknown node type: {node_type}", "warning")

    # A node that reported failure must not silently feed its children. Without
    # this, a rejected entry order still let the hedge leg place and the "trade
    # placed" alert fire, leaving a naked position and a run marked completed.
    if isinstance(result, dict) and result.get("status") == "error":
        # `FlowOpenAlgoClient._handle_response` reports a broker or service
        # failure under "error"; nodes that build their own failure dict use
        # "message". Reading only one of them turned every broker rejection --
        # insufficient funds, RMS block, market closed -- into the literal
        # string "node failed", in the run record and in the webhook reply.
        message = result.get("message") or result.get("error") or "node failed"
        executor.errors.append({"node": node_id, "type": node_type, "message": message})
        if "condition" in result:
            # A condition that could not be evaluated takes neither branch, so
            # the `errored` handling below already stops the descent. It must
            # still be recorded: exempting it from executor.errors meant a
            # workflow whose only fault was an unevaluatable gate finished as
            # `completed` and answered HTTP 200 success, which is exactly the
            # dishonesty this list exists to prevent.
            executor.log(f"{node_type} could not be evaluated ({message})", "error")
        else:
            executor.log(f"Stopping this branch: {node_type} node failed ({message})", "error")
            return

    # Determine which edges to follow
    edges_to_follow = edge_map.get(node_id, [])

    # For condition nodes, filter edges based on the truthy/falsy source handle.
    # Different node types emit different handle vocabularies — NotGate and
    # TimeCondition use "yes"/"no", while PositionCheck, FundCheck,
    # PriceCondition, and TimeWindow use "true"/"false". Treat them as synonyms
    # so all condition forks are honored regardless of which node produced them.
    if result and "condition" in result:
        condition_met = result.get("condition", False)
        # Only a condition that actually evaluated is recorded. A gate treats
        # `get_condition_result(source) is not None` as "this input is settled",
        # so storing the placeholder False of an errored condition made the gate
        # fire on it: an AND gate whose other input was True computed
        # [False, True] -> False and drove its FALSE branch to a real order. The
        # run was marked failed afterwards, by which point the order had been
        # sent. Leaving it unset keeps the gate pending, which is what the
        # branch-suppression below already assumes.
        if result.get("status") != "error":
            context.set_condition_result(node_id, condition_met)
        TRUE_HANDLES = {"yes", "true"}
        FALSE_HANDLES = {"no", "false"}
        # A condition that could not be evaluated (e.g. an operand that did
        # not resolve to a number) must take NEITHER branch. Treating it as
        # False would route the else-path — on a "RSI < 70 -> BUY else SELL"
        # graph a typo'd variable would silently fire the SELL. Pass-through
        # edges (logging/alerting) still run so the failure is visible.
        errored = result.get("status") == "error"
        # A wire into a logic gate carries the source condition's VALUE, not
        # control flow: the gate reads each input's stored boolean and ignores
        # the handle the wire left from. Branch-filtering these edges meant a
        # False input never travelled to the gate, so the gate stayed parked on
        # "waiting for N more input(s)" and never fired at all — an OR with one
        # True and one False produced nothing (OR behaved like AND), no gate
        # could ever drive its False branch, and which input happened to be
        # evaluated last decided the outcome. The gate's own once-per-run guard
        # is what prevents double firing, so always delivering these edges does
        # not reintroduce the duplicate orders the wait was added to stop.
        gate_ids = {
            n.get("id")
            for n in nodes
            if isinstance(n, dict) and n.get("type") in GATE_NODE_TYPES
        }
        filtered_edges = []
        for edge in edges_to_follow:
            source_handle = edge.get("sourceHandle", "") or ""
            is_branch_handle = source_handle in TRUE_HANDLES or source_handle in FALSE_HANDLES
            if errored:
                # An errored condition has no trustworthy boolean, so it must
                # not feed a gate either; the gate stays pending and nothing
                # downstream of it fires.
                if not is_branch_handle:
                    filtered_edges.append(edge)
            elif edge.get("target") in gate_ids:
                filtered_edges.append(edge)
            elif condition_met and source_handle in TRUE_HANDLES:
                filtered_edges.append(edge)
            elif not condition_met and source_handle in FALSE_HANDLES:
                filtered_edges.append(edge)
            elif not is_branch_handle:
                # Edge has no condition handle — pass-through (e.g. a Log node
                # wired to the node's main bottom handle, not the True/False forks).
                filtered_edges.append(edge)
        edges_to_follow = filtered_edges

    # Execute connected nodes
    for edge in edges_to_follow:
        target_id = edge.get("target")
        if target_id:
            execute_node_chain(
                target_id,
                nodes,
                edge_map,
                incoming_edge_map,
                executor,
                context,
                visited_count,
                depth + 1,
            )


def execute_workflow(
    workflow_id: int, webhook_data: dict[str, Any] | None = None, api_key: str = None
) -> dict:
    """Execute a workflow synchronously"""
    lock = get_workflow_lock(workflow_id)

    # Try-acquire, not locked()-then-acquire. The two-step form let both callers
    # observe an unlocked lock; the loser then blocked on the acquire and ran the
    # whole workflow again the moment the winner finished, duplicating every
    # order instead of returning already_running.
    if not lock.acquire(blocking=False):
        logger.warning(f"Workflow {workflow_id} is already running")
        return {
            "status": "error",
            "message": "Workflow is already running",
            "already_running": True,
        }

    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return {"status": "error", "message": "Workflow not found"}

        # Every trigger converges here - schedules, price alerts, order updates,
        # webhooks and Run Now - so this is the only place that can guarantee an
        # incomplete graph never reaches the broker. Guarding the HTTP routes
        # alone left the background triggers unchecked, and saving deliberately
        # accepts a half-built graph. Checked before the execution record exists,
        # so a rejected run is not logged as one that started.
        from services.flow_workflow_validator import validate_workflow

        validation_errors = validate_workflow(
            {
                "name": workflow.name,
                "nodes": workflow.nodes or [],
                "edges": workflow.edges or [],
            },
            strict=True,
        )
        if validation_errors:
            message = validation_errors[0]["message"]
            logger.error(
                f"Workflow {workflow_id} ({workflow.name}) is not runnable: {message}"
            )
            return {
                "status": "error",
                "message": f"Workflow cannot be executed: {message}",
                "errors": validation_errors,
            }

        execution = create_execution(workflow_id, status="running")
        if not execution:
            return {"status": "error", "message": "Failed to create execution record"}

        logs = []
        context = WorkflowContext(workflow_id=workflow_id)

        if webhook_data:
            context.set_variable("webhook", webhook_data)
            logger.info(f"Webhook data injected: {webhook_data}")

        try:
            if not api_key:
                raise Exception("API key required for workflow execution")

            client = get_flow_client(api_key)
            executor = NodeExecutor(client, context, logs, default_strategy=workflow.name)
            logger.info(f"Starting workflow: {workflow.name}")
            executor.log(f"Starting workflow: {workflow.name}")

            nodes = workflow.nodes or []
            edges = workflow.edges or []

            # Find trigger node
            trigger_types = ["start", "webhookTrigger", "priceAlert", "orderUpdateTrigger"]
            start_node = next((n for n in nodes if n.get("type") in trigger_types), None)
            if not start_node:
                raise Exception("No trigger node found")

            # Build edge maps
            edge_map: dict[str, list[dict]] = {}
            incoming_edge_map: dict[str, list[dict]] = {}
            for edge in edges:
                source = edge["source"]
                target = edge["target"]
                if source not in edge_map:
                    edge_map[source] = []
                edge_map[source].append(edge)
                if target not in incoming_edge_map:
                    incoming_edge_map[target] = []
                incoming_edge_map[target].append(edge)

            visited_count: dict[str, int] = {}

            execute_node_chain(
                start_node["id"],
                nodes,
                edge_map,
                incoming_edge_map,
                executor,
                context,
                visited_count,
                depth=0,
            )

            if executor.errors:
                summary = "; ".join(f"{e['type']}: {e['message']}" for e in executor.errors)
                update_execution_status(execution.id, "failed", error=summary, logs=logs)
                return {
                    "status": "error",
                    "message": (
                        f"{len(executor.errors)} node(s) failed: {summary}"
                    ),
                    "execution_id": execution.id,
                    "errors": executor.errors,
                    "logs": logs,
                }

            update_execution_status(execution.id, "completed", logs=logs)
            return {
                "status": "success",
                "message": "Workflow executed successfully",
                "execution_id": execution.id,
                "logs": logs,
            }

        except Exception as e:
            logger.exception(f"Workflow execution failed: {e}")
            logs.append(
                {
                    "time": datetime.now().isoformat(),
                    "message": f"Error: {str(e)}",
                    "level": "error",
                }
            )
            update_execution_status(execution.id, "failed", error=str(e), logs=logs)
            return {
                "status": "error",
                "message": str(e),
                "execution_id": execution.id,
                "logs": logs,
            }

    finally:
        lock.release()
