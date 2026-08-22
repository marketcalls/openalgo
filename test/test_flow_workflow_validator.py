"""Structural validation and catalog-parity tests for Flow workflows.

The parity tests are the important ones: the Flow node catalog is maintained in
several places (ReactFlow registry, palette, config titles, default data, and
the backend validator), and every drift found in the QA audit - a node with no
palette entry, a node with no defaults, a node missing from the documented type
list - was a case of those falling out of step with no test to catch it.

Run: uv run pytest test/test_flow_workflow_validator.py -v
"""

import re
from pathlib import Path

import pytest

from services.flow_workflow_validator import (
    BRANCHING_NODE_TYPES,
    TRIGGER_NODE_TYPES,
    VALID_NODE_TYPES,
    migrate_legacy_node_data,
    validate_workflow,
)
from services.option_symbol_service import parse_underlying_symbol

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"
REGISTRY = FRONTEND / "components" / "flow" / "nodes" / "index.ts"
PALETTE = FRONTEND / "components" / "flow" / "panels" / "NodePalette.tsx"
CONFIG_PANEL = FRONTEND / "components" / "flow" / "panels" / "ConfigPanel.tsx"
CONSTANTS = FRONTEND / "lib" / "flow" / "constants.ts"


def _registry_types() -> set[str]:
    src = REGISTRY.read_text()
    block = src.split("export const nodeTypes = {")[1].split("} as const")[0]
    return set(re.findall(r"^\s*(\w+):\s*\w+Node,", block, re.M))


def _default_node_data_keys() -> set[str]:
    src = CONSTANTS.read_text()
    block = src.split("DEFAULT_NODE_DATA")[1]
    block = block[: block.index("\n}")]
    return set(re.findall(r"^\s{2}(\w+):\s*\{", block, re.M))


def _palette_types() -> set[str]:
    return set(re.findall(r"type: '(\w+)',", PALETTE.read_text()))


def _node_titles() -> set[str]:
    src = CONFIG_PANEL.read_text()
    block = src[src.index("const NODE_TITLES") :]
    block = block[: block.index("\n}")]
    return set(re.findall(r"^\s*(\w+):\s*'", block, re.M))


@pytest.mark.skipif(not REGISTRY.exists(), reason="frontend sources not present")
def test_validator_matches_reactflow_registry():
    """A node the editor can create but the validator rejects is unimportable."""
    assert _registry_types() == set(VALID_NODE_TYPES)


@pytest.mark.skipif(not CONSTANTS.exists(), reason="frontend sources not present")
def test_every_registered_node_has_default_data():
    """Without defaults a dragged node starts as {} and its contract is implicit."""
    assert _registry_types() - _default_node_data_keys() == set()


@pytest.mark.skipif(not PALETTE.exists(), reason="frontend sources not present")
def test_every_registered_node_is_in_the_palette():
    """A registered node missing from the palette cannot be added by a no-code user."""
    assert _registry_types() - _palette_types() == set()


@pytest.mark.skipif(not CONFIG_PANEL.exists(), reason="frontend sources not present")
def test_every_registered_node_has_a_config_title():
    assert _registry_types() - _node_titles() == set()


def _wf(nodes, edges=None, name="W"):
    return {"name": name, "nodes": nodes, "edges": edges or []}


def _node(node_id, node_type="log", **data):
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def _single_action_workflow(node_type, data):
    return _wf(
        [_node("start", "start"), _node("action", node_type, **data)],
        [{"id": "edge", "source": "start", "target": "action"}],
    )


def _strict_node_errors(node_type, data):
    return validate_workflow(_wf([_node("trigger", node_type, **data)]))


def _permissive_node_errors(node_type, data):
    return validate_workflow(
        _wf([_node("trigger", node_type, **data)]), require_name=False, strict=False
    )


@pytest.mark.parametrize(
    ("data", "missing"),
    [
        ({"indicatorName": "RSI", "sourceSeries": "{{bars}}"}, set()),
        ({"indicatorName": "RSI"}, {"symbol", "exchange"}),
        ({"sourceSeries": "{{bars}}"}, {"indicatorName"}),
    ],
)
def test_indicator_requirements_follow_its_data_source(data, missing):
    """History fields must not be required when an upstream series is selected."""
    errors = validate_workflow(_single_action_workflow("indicator", data))
    paths = {
        error["path"].rsplit("/", 1)[-1]
        for error in errors
        if error["code"] == "missing_required_field"
    }
    assert paths == missing


@pytest.mark.parametrize(
    ("quantity", "invalid"),
    [(0, False), ("0", False), (-1, True), (1, False)],
)
def test_smart_order_quantity_allows_zero_but_rejects_negative_values(quantity, invalid):
    """Target-position SmartOrders use zero for square-off semantics."""
    errors = validate_workflow(
        _single_action_workflow(
            "smartOrder",
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": quantity},
        )
    )
    assert any(error["code"] == "invalid_quantity" for error in errors) is invalid


def test_place_order_quantity_must_stay_positive():
    """A regular broker order with zero quantity remains malformed."""
    errors = validate_workflow(
        _single_action_workflow(
            "placeOrder",
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 0},
        )
    )
    assert any(error["code"] == "invalid_quantity" for error in errors)


@pytest.mark.parametrize(
    "data",
    [
        {"orderId": "241001000000001", "status": "complete"},
        {"symbol": "RELIANCE", "status": " TRIGGER_PENDING "},
    ],
)
def test_order_update_trigger_accepts_watchable_filters_and_normalized_status(data):
    """Activation must accept the same filters and status spellings as the monitor."""
    errors = _strict_node_errors("orderUpdateTrigger", data)
    assert not any(error["path"].endswith(("/orderId", "/symbol", "/status")) for error in errors)


@pytest.mark.parametrize("data", [{}, {"orderId": "{{previous.orderid}}"}])
def test_order_update_trigger_rejects_unwatchable_filters(data):
    """A trigger without a literal order ID or symbol can never match an update."""
    errors = _strict_node_errors("orderUpdateTrigger", {"status": "complete", **data})
    assert any(error["code"] in {"missing_alternative", "invalid_trigger_filter"} for error in errors)


def test_order_update_trigger_rejects_unknown_status():
    errors = _strict_node_errors(
        "orderUpdateTrigger", {"orderId": "241001000000001", "status": "filled"}
    )
    assert any(
        error["code"] == "invalid_status" and error["path"].endswith("/status")
        for error in errors
    )


@pytest.mark.parametrize("status", ["filled", 123])
def test_order_update_trigger_rejects_invalid_statuses_when_drafts_are_saved(status):
    """A supplied status typo is malformed data, not an incomplete draft."""
    errors = _permissive_node_errors(
        "orderUpdateTrigger", {"orderId": "241001000000001", "status": status}
    )
    assert any(
        error["code"] == "invalid_status" and error["path"].endswith("/status")
        for error in errors
    )


@pytest.mark.parametrize(
    ("field", "value", "other_filter"),
    [
        ("orderId", 123, {"symbol": "RELIANCE"}),
        ("symbol", ["RELIANCE"], {"orderId": "241001000000001"}),
    ],
)
def test_order_update_trigger_rejects_non_string_filters_when_drafts_are_saved(
    field, value, other_filter
):
    """Monitor matching requires literal string filters, never arbitrary truthy objects."""
    errors = _permissive_node_errors(
        "orderUpdateTrigger", {"status": "complete", field: value, **other_filter}
    )
    assert any(
        error["code"] == "invalid_type" and error["path"].endswith(f"/{field}")
        for error in errors
    )


@pytest.mark.parametrize(
    ("node_type", "data", "requires_expiry"),
    [
        ("optionSymbol", {"underlying": "NIFTY", "optionType": "CE", "expiryDate": "27AUG26"}, False),
        ("optionSymbol", {"underlying": "NIFTY27AUG26", "optionType": "CE"}, False),
        ("optionSymbol", {"underlying": "NIFTY", "optionType": "CE"}, True),
        ("optionChain", {"underlying": "NIFTY", "expiryDate": "27AUG26"}, False),
        ("optionChain", {"underlying": "NIFTY27AUG26"}, False),
        ("optionChain", {"underlying": "NIFTY"}, True),
        ("syntheticFuture", {"underlying": "NIFTY", "expiryDate": "27AUG26"}, False),
        ("syntheticFuture", {"underlying": "NIFTY"}, True),
        ("optionChain", {"underlying": "{{previous.underlying}}"}, False),
    ],
)
def test_expiry_requirement_follows_node_and_underlying(node_type, data, requires_expiry):
    """Only parsable embedded expiries can replace an explicit expiry field."""
    assert parse_underlying_symbol("NIFTY27AUG26")[1] == "27AUG26"
    errors = validate_workflow(_single_action_workflow(node_type, data))
    has_expiry_error = any(
        error["code"] == "missing_required_field" and error["path"].endswith("/expiryDate")
        for error in errors
    )
    assert has_expiry_error is requires_expiry


def test_valid_workflow_passes():
    wf = _wf(
        [_node("n1", "start"), _node("n2", "log", message="hi")],
        [{"id": "e1", "source": "n1", "target": "n2"}],
    )
    assert validate_workflow(wf) == []


@pytest.mark.parametrize("recipient", [None, ""])
def test_whatsapp_alert_allows_self_send_without_recipient(recipient):
    alert_data = {"message": "Workflow executed successfully"}
    if recipient is not None:
        alert_data["to"] = recipient

    wf = _wf(
        [_node("t", "start"), _node("wa", "whatsappAlert", **alert_data)],
        [{"id": "e1", "source": "t", "target": "wa"}],
    )

    assert validate_workflow(wf) == []


def test_whatsapp_alert_still_requires_a_message():
    wf = _wf(
        [_node("t", "start"), _node("wa", "whatsappAlert", to="")],
        [{"id": "e1", "source": "t", "target": "wa"}],
    )

    errors = validate_workflow(wf)

    assert any(error["path"] == "/nodes/1/data/message" for error in errors)


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"nodes": [], "edges": []}, "required"),
        ({"name": "W", "edges": []}, "required"),
        ({"name": "W", "nodes": []}, "required"),
        (_wf([{"id": "a", "type": "NotARealNode", "position": {"x": 0, "y": 0}, "data": {}}]),
         "unknown_node_type"),
        (_wf([{"type": "start", "position": {"x": 0, "y": 0}, "data": {}}]), "required"),
        (_wf([{"id": "a", "type": "start", "position": {"x": 0, "y": 0}}]), "required"),
        (_wf([{"id": "a", "type": "start", "data": {}}]), "required"),
        (_wf([_node("a", "start"), _node("a", "log")]), "duplicate"),
        (_wf([_node("n1", "start")], [{"id": "e1", "source": "n1", "target": "ghost"}]),
         "dangling_edge"),
        (_wf([_node("a", "start"), _node("b", "start")]), "multiple_triggers"),
        (_wf([_node("a", "log")]), "no_trigger"),
        (["not", "an", "object"], "invalid_type"),
    ],
)
def test_rejects_malformed_workflows(payload, code):
    assert any(e["code"] == code for e in validate_workflow(payload))


def test_rejects_the_invented_schema_shape():
    """The shape LLMs commonly invent: strategy/settings/variables/flow."""
    payload = {"strategy": "Gap fill", "settings": {}, "variables": {}, "flow": []}
    errors = validate_workflow(payload)
    assert {e["path"] for e in errors} >= {"/name", "/nodes", "/edges"}


def test_errors_carry_a_path_and_a_code():
    errors = validate_workflow({"name": "W", "nodes": [{"type": "start"}], "edges": []})
    assert errors
    for err in errors:
        assert err["path"].startswith("/")
        assert err["code"] and err["message"]


def test_trigger_types_are_registered_node_types():
    assert TRIGGER_NODE_TYPES <= VALID_NODE_TYPES


def test_detects_a_cycle():
    """A cycle burns the executor's visit budget instead of reporting a loop."""
    wf = _wf(
        [_node("t", "start"), _node("a"), _node("b")],
        [
            {"id": "e1", "source": "t", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
            {"id": "e3", "source": "b", "target": "a"},
        ],
    )
    assert any(e["code"] == "cycle" for e in validate_workflow(wf))


def test_detects_unreachable_nodes():
    wf = _wf(
        [_node("t", "start"), _node("a"), _node("orphan")],
        [{"id": "e1", "source": "t", "target": "a"}],
    )
    assert any(e["code"] == "unreachable" for e in validate_workflow(wf))


@pytest.mark.parametrize(
    "source_type,handle,expected_error",
    [
        ("varCondition", "maybe", True),
        ("varCondition", "true", False),
        ("varCondition", "no", False),
        ("getQuote", "true", True),
    ],
)
def test_validates_source_handles(source_type, handle, expected_error):
    """A handle the source node cannot emit silently drops that branch."""
    wf = _wf(
        [
            _node("t", "start"),
            _node("c", source_type, symbol="X", exchange="NSE", leftValue="{{x}}", operator=">"),
            _node("a"),
        ],
        [
            {"id": "e1", "source": "t", "target": "c"},
            {"id": "e2", "source": "c", "target": "a", "sourceHandle": handle},
        ],
    )
    found = any(e["code"] == "invalid_source_handle" for e in validate_workflow(wf))
    assert found is expected_error


def test_requires_order_fields():
    wf = _wf(
        [_node("t", "start"), _node("o", "placeOrder", exchange="NSE", action="BUY")],
        [{"id": "e1", "source": "t", "target": "o"}],
    )
    assert any(e["code"] == "missing_required_field" for e in validate_workflow(wf))


def test_rejects_a_workflow_with_no_nodes():
    assert any(e["code"] == "no_trigger" for e in validate_workflow(_wf([])))


def test_partial_graphs_stay_savable():
    """The editor saves while a graph is still being wired.

    Structure is always enforced; completeness only at import and activation.
    """
    half = _wf([_node("t", "start"), _node("o", "placeOrder")], [])
    assert validate_workflow(half, require_name=False, strict=False) == []
    assert validate_workflow(half) != []


def test_corrupt_graphs_are_rejected_even_when_saving():
    corrupt = _wf([{"id": "a", "type": "NotReal", "position": {"x": 0, "y": 0}, "data": {}}])
    errors = validate_workflow(corrupt, require_name=False, strict=False)
    assert any(e["code"] == "unknown_node_type" for e in errors)


NODE_COMPONENT_DIR = FRONTEND / "components" / "flow" / "nodes"


@pytest.mark.skipif(not NODE_COMPONENT_DIR.exists(), reason="frontend sources not present")
def test_branching_set_matches_components_that_render_branch_handles():
    """A node whose own handles the validator rejects cannot be imported.

    priceAlert renders true/false handles like the condition nodes, and leaving
    it out made a valid workflow fail validation on its own edges.
    """
    rendering = set()
    for path in NODE_COMPONENT_DIR.glob("*Node.tsx"):
        text = path.read_text()
        if re.search(r'id="(true|false|yes|no)"', text):
            name = path.stem[: -len("Node")]
            rendering.add(name[0].lower() + name[1:])
    rendering -= {"base"}  # shared base component, not a node type
    rendering &= VALID_NODE_TYPES
    assert rendering <= BRANCHING_NODE_TYPES, sorted(rendering - BRANCHING_NODE_TYPES)


def test_malformed_gate_input_count_does_not_crash():
    """A malformed payload must be rejected, not raise out of the validator."""
    wf = _wf([_node("g", "andGate")])
    wf["nodes"][0]["data"]["inputCount"] = "abc"
    validate_workflow(wf)  # must not raise


def test_empty_split_order_is_rejected():
    wf = _wf(
        [_node("t", "start"), _node("s", "splitOrder")],
        [{"id": "e1", "source": "t", "target": "s"}],
    )
    assert any(e["code"] == "missing_required_field" for e in validate_workflow(wf))


def test_phantom_handle_on_a_non_branching_node_is_rejected():
    wf = _wf(
        [_node("t", "start"), _node("q", "getQuote", symbol="X", exchange="NSE"), _node("a")],
        [
            {"id": "e1", "source": "t", "target": "q"},
            {"id": "e2", "source": "q", "target": "a", "sourceHandle": "output-9"},
        ],
    )
    assert any(e["code"] == "invalid_source_handle" for e in validate_workflow(wf))


def test_price_alert_may_use_its_own_branch_handles():
    wf = _wf(
        [
            _node("t", "priceAlert", symbol="X", exchange="NSE", condition="above", price=100),
            _node("a"),
        ],
        [{"id": "e1", "source": "t", "target": "a", "sourceHandle": "true"}],
    )
    assert not any(e["code"] == "invalid_source_handle" for e in validate_workflow(wf))


@pytest.mark.parametrize(
    "operator,expected_condition",
    [("gt", "quantity_above"), ("lt", "quantity_below"), ("weird", None)],
)
def test_position_check_migration_preserves_the_comparison(operator, expected_condition):
    """Flattening every legacy operator to "exists" turns a guard into a no-op."""
    nodes = [_node("p", "positionCheck", operator=operator, threshold=5)]
    migrated, _ = migrate_legacy_node_data(nodes)
    assert migrated[0]["data"].get("condition") == expected_condition
    assert migrated[0]["data"].get("threshold") == 5


def test_fund_check_migration_never_reverses_the_guard():
    """fundCheck only expresses a minimum, so a legacy less-than is left alone."""
    migrated, notes = migrate_legacy_node_data(
        [_node("f", "fundCheck", operator="gt", threshold=10000)]
    )
    assert migrated[0]["data"] == {"minAvailable": 10000}

    migrated, notes = migrate_legacy_node_data(
        [_node("f", "fundCheck", operator="lt", threshold=10000)]
    )
    assert "minAvailable" not in migrated[0]["data"]
    assert any("no equivalent" in note for note in notes)


@pytest.mark.parametrize(
    "condition,data,expect_error",
    [
        ("above", {"price": 100}, False),
        ("above", {}, True),
        ("entering_channel", {"priceLower": 90, "priceUpper": 110}, False),
        ("entering_channel", {"price": 100}, True),
        ("moving_up_percent", {"percentage": 2}, False),
    ],
)
def test_price_alert_requirements_follow_the_condition(condition, data, expect_error):
    """A channel alert has no single price, so requiring one rejected a valid alert."""
    wf = _wf(
        [
            _node("t", "priceAlert", symbol="X", exchange="NSE", condition=condition, **data),
            _node("a", "log", message="hi"),
        ],
        [{"id": "e1", "source": "t", "target": "a"}],
    )
    errors = [e for e in validate_workflow(wf) if e["code"] == "missing_required_field"]
    assert bool(errors) is expect_error


@pytest.mark.parametrize(
    "condition",
    ["above", "price_above", "crosses_above", "cross_above", "crosses", "ABOVE", " above "],
)
def test_every_level_alias_requires_a_price(condition):
    """The monitor accepts several spellings; each must still need a target.

    Keying the requirement on the editor's spellings alone let an alias such as
    `price_above` activate with no price and then run against a zero target.
    """
    wf = _wf(
        [
            _node("t", "priceAlert", symbol="X", exchange="NSE", condition=condition),
            _node("a", "log", message="hi"),
        ],
        [{"id": "e1", "source": "t", "target": "a"}],
    )
    assert any(e["code"] == "missing_required_field" for e in validate_workflow(wf))


def test_unknown_alert_condition_is_rejected():
    """A condition the monitor cannot evaluate would sit registered and never fire."""
    wf = _wf(
        [
            _node("t", "priceAlert", symbol="X", exchange="NSE", condition="abov", price=100),
            _node("a", "log", message="hi"),
        ],
        [{"id": "e1", "source": "t", "target": "a"}],
    )
    assert any(e["code"] == "unknown_condition" for e in validate_workflow(wf))


def test_creating_a_new_workflow_needs_no_graph():
    """The editor creates a strategy with only a name, before any nodes exist.

    Requiring nodes/edges here rejected every "New Strategy" click with a 400.
    Mirrors blueprints.flow.create_workflow: validate only what was sent.
    """

    def create_route(data):
        if "nodes" in data or "edges" in data:
            return validate_workflow(
                {
                    "name": data.get("name") or "",
                    "nodes": data.get("nodes") or [],
                    "edges": data.get("edges") or [],
                },
                require_name=False,
                strict=False,
            )
        return []

    assert create_route({"name": "My Strategy"}) == []
    assert create_route({"name": "My Strategy", "description": "x"}) == []
    assert create_route({"name": "My Strategy", "nodes": [], "edges": []}) == []
    # A graph that is sent is still checked.
    corrupt = {
        "name": "S",
        "nodes": [{"id": "a", "type": "Nope", "position": {"x": 0, "y": 0}, "data": {}}],
        "edges": [],
    }
    assert any(e["code"] == "unknown_node_type" for e in create_route(corrupt))


def test_a_complete_editor_built_strategy_activates():
    """End-to-end shape the editor produces, including a true-branch edge."""
    nodes = [
        _node("n1", "start", scheduleType="interval", intervalValue=1, intervalUnit="minutes"),
        _node("n2", "getQuote", symbol="RELIANCE", exchange="NSE", outputVariable="q"),
        _node("n3", "varCondition", leftValue="{{q.data.ltp}}", operator=">", rightValue="1000"),
        _node(
            "n4",
            "placeOrder",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=1,
        ),
    ]
    edges = [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
        {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "true"},
    ]
    assert validate_workflow(_wf(nodes, edges)) == []
