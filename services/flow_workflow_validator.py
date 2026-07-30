# services/flow_workflow_validator.py
"""Structural validation for Flow workflow payloads.

The editor validates before it posts, but the API is reachable directly, so
without a server-side check a malformed graph is persisted and only fails
later - sometimes at activation, sometimes mid-execution against a live
broker. A workflow that cannot be rendered or executed should never reach the
database in the first place.

This validates *structure*, not trading semantics: shape, identifiers, known
node types, edge endpoints, and the one-trigger rule. Per-node field contracts
stay with the executor, which is where their defaults and coercions live.
"""

import re
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

# The node types the editor can render and the executor can dispatch. Kept in
# lockstep with frontend/src/components/flow/nodes/index.ts; the parity test in
# test/test_flow_workflow_validator.py fails if the two drift.
VALID_NODE_TYPES: frozenset[str] = frozenset(
    {
        "andGate",
        "barOffset",
        "basketOrder",
        "calendar",
        "cancelAllOrders",
        "cancelOrder",
        "closePositions",
        "delay",
        "expiry",
        "fundCheck",
        "funds",
        "getDepth",
        "getOrderStatus",
        "getQuote",
        "group",
        "history",
        "holdings",
        "holidays",
        "httpRequest",
        "indicator",
        "intervals",
        "log",
        "margin",
        "mathExpression",
        "modifyOrder",
        "multiQuotes",
        "notGate",
        "openPosition",
        "optionChain",
        "optionSymbol",
        "optionsMultiOrder",
        "optionsOrder",
        "orGate",
        "orderBook",
        "orderUpdateTrigger",
        "placeOrder",
        "positionBook",
        "positionCheck",
        "priceAlert",
        "priceCondition",
        "priorPeriodOhlc",
        "smartOrder",
        "splitOrder",
        "start",
        "strategyPnl",
        "subscribeDepth",
        "subscribeLtp",
        "subscribeQuote",
        "symbol",
        "syntheticFuture",
        "telegramAlert",
        "timeCondition",
        "timeWindow",
        "timings",
        "tradeBook",
        "unsubscribe",
        "varCondition",
        "variable",
        "waitUntil",
        "webhookTrigger",
        "whatsappAlert",
    }
)

TRIGGER_NODE_TYPES: frozenset[str] = frozenset(
    {"start", "webhookTrigger", "priceAlert", "orderUpdateTrigger"}
)

# Fields required only for particular option values. A channel alert is
# configured with priceLower/priceUpper and has no single `price`, so requiring
# one unconditionally rejected a documented, working alert.
# Fields required only for particular option values, keyed on the *canonical*
# condition the price monitor uses. The editor and the monitor keep separate
# spellings for the same conditions, so the selector is normalized through the
# monitor's own alias table before lookup - keying on the editor's spellings let
# an alias such as `price_above` activate with no target price at all.
CONDITIONAL_REQUIRED_FIELDS: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    "priceAlert": {
        "condition": {
            "greater_than": ("price",),
            "less_than": ("price",),
            "crossing": ("price",),
            "crossing_up": ("price",),
            "crossing_down": ("price",),
            "entering_channel": ("priceLower", "priceUpper"),
            "inside_channel": ("priceLower", "priceUpper"),
            "exiting_channel": ("priceLower", "priceUpper"),
            "outside_channel": ("priceLower", "priceUpper"),
            "moving_up_percent": ("percentage",),
            "moving_down_percent": ("percentage",),
            "moving_up": (),
            "moving_down": (),
        }
    },
}


def _positive_number(value: object) -> float | None:
    """The value as a positive number, or None when it is not one."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _alert_threshold_errors(
    base: str, data: dict, condition: str, required: tuple[str, ...]
) -> list[dict]:
    """Sanity-check the numbers a price alert compares against.

    A zero or negative level is never reached by a real instrument price, and an
    inverted channel is empty, so either would leave the alert registered and
    unable to fire - the same silent non-firing this node has had before.
    """
    errors: list[dict] = []
    for field in required:
        if field not in data:
            continue  # absence is reported as a missing required field
        if _positive_number(data.get(field)) is None:
            errors.append(
                _err(
                    f"{base}/data/{field}",
                    "invalid_threshold",
                    f"{field} must be a positive number for a '{condition}' alert; "
                    f"{data.get(field)!r} can never be reached.",
                    "a positive number",
                    data.get(field),
                )
            )
    lower = _positive_number(data.get("priceLower"))
    upper = _positive_number(data.get("priceUpper"))
    if "priceLower" in required and lower is not None and upper is not None and lower >= upper:
        errors.append(
            _err(
                f"{base}/data/priceLower",
                "invalid_threshold",
                f"priceLower ({lower}) must be below priceUpper ({upper}); "
                "an inverted channel contains no prices.",
                "priceLower < priceUpper",
                [lower, upper],
            )
        )
    return errors


def _canonical_condition(value: object) -> str:
    """Resolve a condition to the name the price monitor compares on.

    Delegated to the monitor so the two cannot drift; falls back to a plain
    normalization if it cannot be imported (docs builds, lint environments).
    """
    try:
        from services.flow_price_monitor_service import FlowPriceMonitor

        return FlowPriceMonitor.normalize_condition(str(value))
    except Exception:
        return str(value or "").strip().lower().replace("-", "_")


# Nodes that exist only in the editor. They are never dispatched, so they are
# exempt from reachability.
DECORATIVE_NODE_TYPES: frozenset[str] = frozenset({"group"})

MAX_NODES = 500
MAX_EDGES = 1000

# Source handles each node kind may emit. Condition nodes and gates fork; the
# executor treats yes/no as synonyms of true/false. Anything else on an edge is
# a typo that silently drops the branch at run time.
_BRANCHING_HANDLES = frozenset({"true", "false", "yes", "no"})
BRANCHING_NODE_TYPES: frozenset[str] = frozenset(
    {
        "positionCheck",
        "fundCheck",
        "priceCondition",
        "varCondition",
        "timeWindow",
        "timeCondition",
        "andGate",
        "orGate",
        "notGate",
        # Renders true/false handles like the condition nodes, so rejecting them
        # made a valid price-alert workflow fail on its own edges.
        "priceAlert",
    }
)

# Fields an order node cannot execute without. Checked here because a workflow
# missing them fails at the broker, mid-session, rather than at import.
REQUIRED_NODE_FIELDS: dict[str, tuple[str, ...]] = {
    "placeOrder": ("symbol", "exchange", "action", "quantity"),
    "smartOrder": ("symbol", "exchange", "action", "quantity"),
    "optionsOrder": ("underlying", "action", "quantity"),
    "modifyOrder": ("orderId",),
    "cancelOrder": ("orderId",),
    "getOrderStatus": ("orderId",),
    "getQuote": ("symbol", "exchange"),
    "getDepth": ("symbol", "exchange"),
    "history": ("symbol", "exchange", "interval"),
    "indicator": ("symbol", "exchange", "indicatorName"),
    "priorPeriodOhlc": ("symbol", "exchange"),
    "barOffset": ("symbol", "exchange"),
    "openPosition": ("symbol", "exchange"),
    "telegramAlert": ("message",),
    "whatsappAlert": ("to", "message"),
    "mathExpression": ("expression",),
    "varCondition": ("leftValue", "operator"),
    "priceCondition": ("symbol", "exchange", "operator"),
    # Broker-mutating nodes. An empty one reaches the broker as a malformed
    # order rather than failing at import.
    "splitOrder": ("symbol", "exchange", "action", "quantity", "splitSize"),
    "basketOrder": ("orders",),
    "optionsMultiOrder": ("underlying", "quantity"),
    # `price` is required only for level conditions - see CONDITIONAL_FIELDS.
    "priceAlert": ("symbol", "exchange", "condition"),
    "subscribeLtp": ("symbol", "exchange"),
    "subscribeQuote": ("symbol", "exchange"),
    "subscribeDepth": ("symbol", "exchange"),
    "optionSymbol": ("underlying", "optionType"),
    "optionChain": ("underlying",),
    "syntheticFuture": ("underlying",),
    "expiry": ("symbol", "exchange"),
    "symbol": ("symbol", "exchange"),
    "multiQuotes": ("symbols",),
    "httpRequest": ("url",),
    "variable": ("variableName",),
    "waitUntil": ("targetTime",),
}


class WorkflowValidationError(Exception):
    """One or more structural problems, each with a path and a reason."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s)")


def _err(path: str, code: str, message: str, expected=None, received=None) -> dict[str, Any]:
    entry = {"path": path, "code": code, "message": message}
    if expected is not None:
        entry["expected"] = expected
    if received is not None:
        entry["received"] = received
    return entry


def validate_workflow(
    payload: Any, *, require_name: bool = True, strict: bool = True
) -> list[dict[str, Any]]:
    """Return a list of errors; empty means the workflow passes.

    Two levels, because the editor saves continuously while a graph is still
    being wired:

    * Always checked (structure) - shape, ids, known node types, edge endpoints,
      branch handles. A graph failing these cannot be rendered and is corrupt
      however incomplete the user\'s work is.
    * ``strict`` only (completeness) - required node fields, exactly one
      trigger, reachability, and cycles. Enforced at import and activation,
      where the workflow is presented as finished, and skipped on save so a
      half-built graph remains savable.
    """
    errors: list[dict[str, Any]] = []

    if not isinstance(payload, dict):
        return [
            _err(
                "/",
                "invalid_type",
                "Workflow must be a JSON object",
                "object",
                type(payload).__name__,
            )
        ]

    name = payload.get("name")
    if require_name and (not isinstance(name, str) or not name.strip()):
        errors.append(_err("/name", "required", "Workflow needs a non-empty name", "string", name))

    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list):
        errors.append(
            _err(
                "/nodes",
                "required",
                "Workflow needs a nodes array",
                "array",
                type(nodes).__name__ if nodes is not None else None,
            )
        )
        nodes = []
    if not isinstance(edges, list):
        errors.append(
            _err(
                "/edges",
                "required",
                "Workflow needs an edges array",
                "array",
                type(edges).__name__ if edges is not None else None,
            )
        )
        edges = []

    if len(nodes) > MAX_NODES:
        errors.append(
            _err(
                "/nodes",
                "too_large",
                f"Workflow has more than {MAX_NODES} nodes",
                MAX_NODES,
                len(nodes),
            )
        )
    if len(edges) > MAX_EDGES:
        errors.append(
            _err(
                "/edges",
                "too_large",
                f"Workflow has more than {MAX_EDGES} edges",
                MAX_EDGES,
                len(edges),
            )
        )

    node_ids: set[str] = set()
    triggers: list[str] = []

    for i, node in enumerate(nodes):
        base = f"/nodes/{i}"
        if not isinstance(node, dict):
            errors.append(
                _err(base, "invalid_type", "Node must be an object", "object", type(node).__name__)
            )
            continue

        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            errors.append(
                _err(
                    f"{base}/id", "required", "Node needs a non-empty string id", "string", node_id
                )
            )
        elif node_id in node_ids:
            errors.append(
                _err(
                    f"{base}/id",
                    "duplicate",
                    f"Duplicate node id '{node_id}'",
                    "unique id",
                    node_id,
                )
            )
        else:
            node_ids.add(node_id)

        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            errors.append(
                _err(f"{base}/type", "required", "Node needs a type", "string", node_type)
            )
        elif node_type not in VALID_NODE_TYPES:
            errors.append(
                _err(
                    f"{base}/type",
                    "unknown_node_type",
                    f"'{node_type}' is not a Flow node type. Node types are "
                    "fixed; inventing one makes the workflow unrenderable.",
                    "one of the documented node types",
                    node_type,
                )
            )
        elif node_type in TRIGGER_NODE_TYPES:
            triggers.append(str(node_id))

        data = node.get("data")
        if strict and isinstance(data, dict) and isinstance(node_type, str):
            required = list(REQUIRED_NODE_FIELDS.get(node_type, ()))
            for selector, options in CONDITIONAL_REQUIRED_FIELDS.get(node_type, {}).items():
                chosen = _canonical_condition(data.get(selector, ""))
                if chosen and chosen not in options:
                    # An unrecognized condition can never evaluate true, so the
                    # trigger would sit registered and silently never fire.
                    errors.append(
                        _err(
                            f"{base}/data/{selector}",
                            "unknown_condition",
                            f"'{data.get(selector)}' is not a condition the price "
                            "monitor can evaluate, so this alert could never fire.",
                            sorted(options),
                            data.get(selector),
                        )
                    )
                required.extend(options.get(chosen, ()))
                errors.extend(_alert_threshold_errors(base, data, chosen, options.get(chosen, ())))
            for field in required:
                value = data.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    errors.append(
                        _err(
                            f"{base}/data/{field}",
                            "missing_required_field",
                            f"A {node_type} node needs {field}. Without it the node "
                            "fails at run time, not at import.",
                            field,
                            value,
                        )
                    )
        if not isinstance(data, dict):
            errors.append(
                _err(
                    f"{base}/data",
                    "required",
                    "Node needs a data object",
                    "object",
                    type(node.get("data")).__name__ if node.get("data") is not None else None,
                )
            )

        position = node.get("position")
        if not isinstance(position, dict):
            errors.append(
                _err(
                    f"{base}/position",
                    "required",
                    "Node needs a position {x, y}",
                    "object",
                    type(position).__name__ if position is not None else None,
                )
            )
        else:
            for axis in ("x", "y"):
                if not isinstance(position.get(axis), (int, float)) or isinstance(
                    position.get(axis), bool
                ):
                    errors.append(
                        _err(
                            f"{base}/position/{axis}",
                            "invalid_type",
                            f"position.{axis} must be a number",
                            "number",
                            position.get(axis),
                        )
                    )

    edge_ids: set[str] = set()
    for i, edge in enumerate(edges):
        base = f"/edges/{i}"
        if not isinstance(edge, dict):
            errors.append(
                _err(base, "invalid_type", "Edge must be an object", "object", type(edge).__name__)
            )
            continue

        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id.strip():
            errors.append(
                _err(
                    f"{base}/id", "required", "Edge needs a non-empty string id", "string", edge_id
                )
            )
        elif edge_id in edge_ids:
            errors.append(
                _err(
                    f"{base}/id",
                    "duplicate",
                    f"Duplicate edge id '{edge_id}'",
                    "unique id",
                    edge_id,
                )
            )
        else:
            edge_ids.add(edge_id)

        for endpoint in ("source", "target"):
            value = edge.get(endpoint)
            if not isinstance(value, str) or not value:
                errors.append(
                    _err(
                        f"{base}/{endpoint}",
                        "required",
                        f"Edge needs a {endpoint} node id",
                        "string",
                        value,
                    )
                )
            elif node_ids and value not in node_ids:
                # A dangling edge renders as a broken connection and silently
                # drops whatever branch it was meant to carry.
                errors.append(
                    _err(
                        f"{base}/{endpoint}",
                        "dangling_edge",
                        f"Edge {endpoint} '{value}' is not a node in this workflow",
                        "an existing node id",
                        value,
                    )
                )

    node_types_by_id = {
        n.get("id"): n.get("type")
        for n in nodes
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    }
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            continue
        handle = edge.get("sourceHandle")
        if handle is None or handle == "":
            continue  # an unconditional edge is legitimate
        source_type = node_types_by_id.get(edge.get("source"))
        if source_type in BRANCHING_NODE_TYPES and str(handle) not in _BRANCHING_HANDLES:
            errors.append(
                _err(
                    f"/edges/{i}/sourceHandle",
                    "invalid_source_handle",
                    f"'{handle}' is not a branch of a {source_type} node, so this edge "
                    "is never followed and its branch is silently dropped.",
                    sorted(_BRANCHING_HANDLES),
                    handle,
                )
            )
        elif source_type and source_type not in BRANCHING_NODE_TYPES:
            # Non-branching nodes render a single unnamed source handle, so any
            # named one is a phantom: the edge points at a socket that does not
            # exist and the branch it carries is silently dropped.
            errors.append(
                _err(
                    f"/edges/{i}/sourceHandle",
                    "invalid_source_handle",
                    f"A {source_type} node has no '{handle}' output handle; it emits a "
                    "single unconditional output.",
                    "no sourceHandle",
                    handle,
                )
            )

    # Gate input slots. `targetHandle: "input-N"` must name a slot the gate
    # actually has: a higher N is never filled, so the gate waits for an input
    # that can never arrive and its branch silently never fires.
    def _slot_count(value) -> int:
        """Gate input count, tolerant of a malformed value.

        Casting directly raised ValueError out of the validator, so a
        malformed payload crashed the request it was supposed to reject.
        """
        try:
            return max(int(value), 1) if value not in (None, "") else 2
        except (TypeError, ValueError):
            return 2

    gate_slots = {
        n.get("id"): _slot_count(n.get("data", {}).get("inputCount"))
        for n in nodes
        if isinstance(n, dict)
        and n.get("type") in ("andGate", "orGate")
        and isinstance(n.get("data"), dict)
    }
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            continue
        handle = edge.get("targetHandle")
        if handle is None or handle == "":
            continue
        slots = gate_slots.get(edge.get("target"))
        if slots is None:
            # Only gates render numbered input slots. Naming one on any other
            # node points the edge at a socket that does not exist.
            if re.fullmatch(r"input-\d+", str(handle)):
                target_type = node_types_by_id.get(edge.get("target"))
                errors.append(
                    _err(
                        f"/edges/{i}/targetHandle",
                        "invalid_target_handle",
                        f"Only gate nodes have numbered input slots; a "
                        f"{target_type or 'non-gate'} node has no '{handle}'.",
                        "no targetHandle",
                        handle,
                    )
                )
            continue
        match = re.fullmatch(r"input-(\d+)", str(handle))
        if not match or int(match.group(1)) >= slots:
            errors.append(
                _err(
                    f"/edges/{i}/targetHandle",
                    "invalid_target_handle",
                    f"'{handle}' is not an input slot on this gate, which has {slots}. "
                    "The gate would wait for an input that never arrives.",
                    [f"input-{n}" for n in range(slots)],
                    handle,
                )
            )

    if strict and not nodes:
        errors.append(
            _err(
                "/nodes",
                "no_trigger",
                "Workflow has no nodes, so it can never run.",
                "at least a trigger node",
                0,
            )
        )
    elif strict and nodes and not triggers:
        errors.append(
            _err(
                "/nodes",
                "no_trigger",
                "Workflow has no trigger node, so it can never run. Add one of: "
                + ", ".join(sorted(TRIGGER_NODE_TYPES)),
                "exactly one trigger",
                0,
            )
        )
    elif strict and len(triggers) > 1:
        # The executor walks from the first trigger it finds; the rest of the
        # graph never executes and nothing reports why.
        errors.append(
            _err(
                "/nodes",
                "multiple_triggers",
                "Workflow has more than one trigger. Only the first would run and "
                "everything downstream of the others would be silently skipped.",
                "exactly one trigger",
                triggers,
            )
        )

    # Only meaningful once ids and endpoints are sound.
    if strict and not errors:
        errors.extend(_graph_errors(nodes, edges, node_ids, triggers))

    return errors


def _graph_errors(nodes: list, edges: list, node_ids: set[str], triggers: list[str]) -> list[dict]:
    """Cycles and nodes the trigger can never reach."""
    errors: list[dict] = []
    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src, dst = edge.get("source"), edge.get("target")
        if src in adjacency and dst in node_ids:
            adjacency[src].append(dst)

    # Cycle detection. The executor caps depth and visits rather than detecting
    # a loop, so a cycle burns the whole budget and truncates the run instead of
    # reporting anything.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(node_ids, WHITE)
    cycle: list[str] = []

    def visit(node: str, path: list[str]) -> bool:
        colour[node] = GREY
        for nxt in adjacency.get(node, ()):
            if colour[nxt] == GREY:
                cycle.extend(path[path.index(nxt) :] + [nxt] if nxt in path else [nxt])
                return True
            if colour[nxt] == WHITE and visit(nxt, path + [nxt]):
                return True
        colour[node] = BLACK
        return False

    for nid in node_ids:
        if colour[nid] == WHITE and visit(nid, [nid]):
            errors.append(
                _err(
                    "/edges",
                    "cycle",
                    "The graph contains a cycle, which runs until the executor's "
                    "visit limit and then truncates rather than reporting a loop: "
                    + " -> ".join(cycle[:6]),
                    "an acyclic graph",
                    cycle[:6],
                )
            )
            break

    # Reachability from the trigger. A node the trigger cannot reach never runs,
    # and nothing at run time says so.
    if triggers:
        seen: set[str] = set()
        stack = list(triggers)
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            stack.extend(adjacency.get(nid, ()))
        # `group` is a visual container with no execution behaviour, so it is
        # legitimately unconnected while the nodes drawn inside it run through
        # their own edges.
        decorative = {
            n.get("id")
            for n in nodes
            if isinstance(n, dict) and n.get("type") in DECORATIVE_NODE_TYPES
        }
        unreachable = sorted(node_ids - seen - decorative)
        if unreachable:
            errors.append(
                _err(
                    "/nodes",
                    "unreachable",
                    "These nodes cannot be reached from the trigger and will never "
                    "run: " + ", ".join(unreachable[:8]),
                    "every node reachable from the trigger",
                    unreachable[:8],
                )
            )
    return errors


def assert_valid_workflow(payload: Any, *, require_name: bool = True, strict: bool = True) -> None:
    """Raise WorkflowValidationError when the workflow does not pass."""
    errors = validate_workflow(payload, require_name=require_name, strict=strict)
    if errors:
        raise WorkflowValidationError(errors)


# Legacy node payloads, and the canonical shape they map to. Applied at import
# so the stored workflow is correct, rather than relying on every reader to
# remember the old spelling forever.
def migrate_legacy_node_data(nodes: list) -> tuple[list, list[str]]:
    """Upgrade legacy node payloads. Returns (nodes, human-readable notes)."""
    notes: list[str] = []
    if not isinstance(nodes, list):
        return nodes, notes

    migrated = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            migrated.append(node)
            continue
        node_type = node.get("type")
        data = dict(node["data"])

        if node_type == "fundCheck" and "minAvailable" not in data and "threshold" in data:
            # fundCheck can only express "at least this much". A legacy
            # greater-than maps cleanly; a legacy less-than means the opposite,
            # and silently reversing a capital guard is worse than refusing to
            # guess, so that one is left for the user to restate.
            operator = str(data.get("operator") or "gt").strip().lower()
            if operator in ("gt", "gte", "ge", ">", ">="):
                data["minAvailable"] = data.pop("threshold")
                data.pop("operator", None)
                notes.append(
                    f"fundCheck '{node.get('id')}': threshold -> minAvailable "
                    f"({data['minAvailable']})"
                )
            else:
                notes.append(
                    f"fundCheck '{node.get('id')}': operator '{operator}' has no "
                    "equivalent - this node only supports a minimum. Left unchanged; "
                    "set Minimum Available yourself."
                )
        elif node_type == "positionCheck" and "condition" not in data and "operator" in data:
            # Preserve the comparison instead of flattening every legacy operator
            # to "exists", which would turn a quantity-based exit into an
            # unconditional one.
            operator = str(data.get("operator") or "").strip().lower()
            mapping = {
                "gt": "quantity_above",
                ">": "quantity_above",
                "gte": "quantity_above",
                "ge": "quantity_above",
                ">=": "quantity_above",
                "lt": "quantity_below",
                "<": "quantity_below",
                "lte": "quantity_below",
                "le": "quantity_below",
                "<=": "quantity_below",
            }
            condition = mapping.get(operator)
            if condition:
                data["condition"] = condition
                data.pop("operator", None)
                notes.append(
                    f"positionCheck '{node.get('id')}': operator '{operator}' -> "
                    f"condition '{condition}' (threshold kept)"
                )
            else:
                notes.append(
                    f"positionCheck '{node.get('id')}': operator '{operator}' has no "
                    "equivalent condition. Left unchanged; set the condition yourself."
                )
        elif node_type == "priceCondition" and "value" not in data and "threshold" in data:
            data["value"] = data.pop("threshold")
            notes.append(f"priceCondition '{node.get('id')}': threshold -> value")

        migrated.append({**node, "data": data})
    return migrated, notes


# Trigger fields that are registered with the scheduler or a monitor at
# activation rather than read per run. A change to any of them needs a
# deactivate/reactivate cycle, which comparing node *types* alone would miss:
# editing an interval from 1m to 5m keeps the same trigger type.
TRIGGER_CONFIG_FIELDS: tuple[str, ...] = (
    # start
    "scheduleType",
    "time",
    "days",
    "executeAt",
    "intervalMinutes",
    "intervalValue",
    "intervalUnit",
    "marketHoursOnly",
    # priceAlert - every field add_alert() captures, including the channel
    # bounds and percentage that only some conditions use
    "symbol",
    "exchange",
    "condition",
    "price",
    "priceLower",
    "priceUpper",
    "percentage",
    "expiration",
    # orderUpdateTrigger
    "orderId",
    "status",
    # shared
    "trigger",
)


def trigger_config(nodes: list) -> dict:
    """The activation-relevant configuration of a graph's trigger node(s).

    Two graphs with equal trigger_config can be swapped under a running
    workflow; anything else needs the workflow reactivated so the scheduler and
    monitors pick the change up.
    """
    config: dict = {}
    if not isinstance(nodes, list):
        return config
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") not in TRIGGER_NODE_TYPES:
            continue
        data = node.get("data") or {}
        if not isinstance(data, dict):
            continue
        config[str(node.get("type"))] = {
            field: data.get(field) for field in TRIGGER_CONFIG_FIELDS if field in data
        }
    return config
