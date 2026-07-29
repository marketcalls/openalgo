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
    TRIGGER_NODE_TYPES,
    VALID_NODE_TYPES,
    validate_workflow,
)

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


def test_valid_workflow_passes():
    wf = _wf(
        [_node("n1", "start"), _node("n2", "log", message="hi")],
        [{"id": "e1", "source": "n1", "target": "n2"}],
    )
    assert validate_workflow(wf) == []


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
