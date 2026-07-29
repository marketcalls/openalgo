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

MAX_NODES = 500
MAX_EDGES = 1000


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


def validate_workflow(payload: Any, *, require_name: bool = True) -> list[dict[str, Any]]:
    """Return a list of structural errors; empty means the workflow is valid."""
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

        if not isinstance(node.get("data"), dict):
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

    if nodes and not triggers:
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
    elif len(triggers) > 1:
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

    return errors


def assert_valid_workflow(payload: Any, *, require_name: bool = True) -> None:
    """Raise WorkflowValidationError when the workflow is structurally invalid."""
    errors = validate_workflow(payload, require_name=require_name)
    if errors:
        raise WorkflowValidationError(errors)
