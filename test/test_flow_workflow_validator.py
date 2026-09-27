"""Structural validation and catalog-parity tests for Flow workflows.

The parity tests are the important ones: the Flow node catalog is maintained in
several places (ReactFlow registry, palette, config titles, default data, and
the backend validator), and every drift found in the QA audit - a node with no
palette entry, a node with no defaults, a node missing from the documented type
list - was a case of those falling out of step with no test to catch it.

Run: uv run pytest test/test_flow_workflow_validator.py -v
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from services.flow_node_contracts import parse_underlying_symbol
from services.flow_workflow_validator import (
    BRANCHING_NODE_TYPES,
    TRIGGER_NODE_TYPES,
    VALID_NODE_TYPES,
    migrate_legacy_node_data,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"
FLOW_IMPORT_PROMPT = ROOT / "docs" / "prompt" / "flow-import-format.md"
REGISTRY = FRONTEND / "components" / "flow" / "nodes" / "index.ts"
PALETTE = FRONTEND / "components" / "flow" / "panels" / "NodePalette.tsx"
CONFIG_PANEL = FRONTEND / "components" / "flow" / "panels" / "ConfigPanel.tsx"
CONSTANTS = FRONTEND / "lib" / "flow" / "constants.ts"
FLOW_TYPES = FRONTEND / "types" / "flow.ts"


def test_validator_import_does_not_require_application_secrets():
    """Static workflow validation must not initialize database-coupled services."""
    env = os.environ.copy()
    env.pop("API_KEY_PEPPER", None)

    result = subprocess.run(
        [sys.executable, "-c", "import services.flow_workflow_validator"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _registry_types() -> set[str]:
    src = REGISTRY.read_text()
    block = src.split("export const nodeTypes = {")[1].split("} as const")[0]
    return set(re.findall(r"^\s*(\w+):\s*\w+Node,", block, re.M))


def _default_node_data_keys() -> set[str]:
    src = CONSTANTS.read_text()
    block = src.split("DEFAULT_NODE_DATA")[1]
    block = block[: block.index("\n}")]
    return set(re.findall(r"^\s{2}(\w+):\s*\{", block, re.M))


def _default_node_data_block(node_type: str) -> str:
    src = CONSTANTS.read_text()
    return src.split(f"  {node_type}: {{", 1)[1].split("\n  },", 1)[0]


def _typescript_interface_body(interface_name: str) -> str:
    src = FLOW_TYPES.read_text()
    return src.split(f"export interface {interface_name} {{", 1)[1].split("\n}", 1)[0]


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


@pytest.mark.parametrize("node_type", ["smartOrder", "basketOrder", "splitOrder"])
@pytest.mark.parametrize("field", ["price", "triggerPrice"])
def test_frontend_order_defaults_include_numeric_prices(node_type, field):
    """New order nodes persist the complete price contract from their first save."""
    block = _default_node_data_block(node_type)
    assert re.search(rf"^\s+{field}: 0,$", block, re.M)


def test_frontend_order_defaults_exclude_legacy_fields():
    """Frontend contracts do not advertise values ignored by execution."""
    assert "username" not in _default_node_data_block("telegramAlert")
    assert "username" not in _typescript_interface_body("TelegramAlertNodeData")

    options_multi = _typescript_interface_body("OptionsMultiOrderNodeData")
    leg = options_multi.split("legs: Array<{", 1)[1].split("}>", 1)[0]
    assert "expiryDate" not in leg


@pytest.mark.parametrize(
    ("interface_name", "optional"),
    [
        ("OptionsOrderNodeData", False),
        ("OptionsMultiOrderNodeData", False),
        ("BasketOrderNodeData", True),
        ("SplitOrderNodeData", False),
    ],
)
def test_frontend_order_defaults_types_accept_every_backend_price_type(interface_name, optional):
    """Order interfaces cannot reject a price type accepted by execution."""
    body = _typescript_interface_body(interface_name)
    marker = "priceType?:" if optional else "priceType:"
    assert f"{marker} 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'" in body


@pytest.mark.parametrize(
    "interface_name",
    [
        "OptionsOrderNodeData",
        "OptionsMultiOrderNodeData",
        "BasketOrderNodeData",
        "SplitOrderNodeData",
    ],
)
@pytest.mark.parametrize("field", ["price", "triggerPrice"])
def test_frontend_order_defaults_types_expose_top_level_prices(interface_name, field):
    """Every priced order exposes both persisted numeric fields at the top level."""
    body = _typescript_interface_body(interface_name)
    top_level = body.split("}>", 1)[1] if interface_name == "OptionsMultiOrderNodeData" else body
    assert f"{field}?: number" in top_level


@pytest.mark.parametrize(
    "field",
    [
        "product?: 'MIS' | 'NRML'",
        "priceType?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'",
        "price?: number",
        "triggerPrice?: number",
    ],
)
def test_frontend_order_defaults_custom_legs_carry_price_contract(field):
    """Imported custom legs retain their own execution fields, but not expiry."""
    body = _typescript_interface_body("OptionsMultiOrderNodeData")
    leg = body.split("legs: Array<{", 1)[1].split("}>", 1)[0]
    assert field in leg


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


JSON_FENCE_RE = re.compile(r"^```json\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
MULTI_VALUE_JSON_FENCES = {5: 2, 28: 2, 39: 5}


def _json_fences(prompt):
    for index, match in enumerate(JSON_FENCE_RE.finditer(prompt), 1):
        start_line = prompt.count("\n", 0, match.start()) + 1
        yield index, start_line, match.group(1)


def _decode_json_sequence(raw):
    decoder = json.JSONDecoder()
    values = []
    offset = 0
    while True:
        while offset < len(raw) and raw[offset].isspace():
            offset += 1
        if offset == len(raw):
            return values
        value, offset = decoder.raw_decode(raw, offset)
        values.append(value)


def _markdown_section(prompt, heading_prefix):
    """Return one Markdown section, including subsections but not its next peer."""
    match = re.search(rf"^{re.escape(heading_prefix)}(?:\s.*)?$", prompt, re.MULTILINE)
    assert match is not None, f"missing prompt heading: {heading_prefix}"
    heading_level = len(heading_prefix) - len(heading_prefix.lstrip("#"))
    rest = prompt[match.end() :]
    next_heading = re.search(rf"^#{{1,{heading_level}}}\s", rest, re.MULTILINE)
    return prompt[match.start() : match.end() + (next_heading.start() if next_heading else len(rest))]


def _walk_json(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _prompt_json_nodes(prompt):
    """Yield every node embedded in every value from every decoded JSON fence."""
    for fence_index, start_line, raw in _json_fences(prompt):
        for value_index, value in enumerate(_decode_json_sequence(raw), 1):
            for candidate in _walk_json(value):
                if (
                    isinstance(candidate, dict)
                    and isinstance(candidate.get("type"), str)
                    and isinstance(candidate.get("data"), dict)
                ):
                    yield fence_index, start_line, value_index, candidate


def test_prompt_prose_documents_every_repaired_flow_contract():
    """The human-facing contract must retain every correction behind the examples."""
    prompt = FLOW_IMPORT_PROMPT.read_text(encoding="utf-8")
    failures = []

    def require(category, condition, detail):
        if not condition:
            failures.append(f"{category}: {detail}")

    trigger = _markdown_section(prompt, "### 7.1 Trigger nodes")
    require(
        "second_trigger",
        "reject a second trigger" in trigger and "permit a second trigger" not in trigger,
        "strict validation must explicitly reject a second trigger",
    )

    history = _markdown_section(prompt, "#### history")
    require(
        "history_range",
        all(field in history for field in ("`days`", "`startDate`", "`endDate`"))
        and "explicit range takes\nprecedence over `days`" in history,
        "document days plus start/end dates and explicit-range precedence",
    )

    holidays = _markdown_section(prompt, "#### holidays")
    require(
        "holidays_year",
        "`year`" in holidays and "`exchange`" not in holidays,
        "holidays must document year, not exchange",
    )
    timings = _markdown_section(prompt, "#### timings")
    require(
        "timings_date",
        "`date`" in timings and "`exchange`" not in timings,
        "timings must document date, not exchange",
    )

    variable = _markdown_section(prompt, "#### variable")
    operation_table = variable.split("| Operation | Behaviour |", 1)[-1].split(
        "| Field | Type | Default | Notes |", 1
    )[0]
    documented_operations = set(re.findall(r'^\| `"([^"]+)"` \|', operation_table, re.M))
    required_operations = {
        "set",
        "get",
        "add",
        "subtract",
        "multiply",
        "divide",
        "increment",
        "decrement",
        "parse_json",
        "stringify",
        "append",
    }
    require(
        "variable_operations",
        documented_operations == required_operations,
        f"expected exactly eleven operations; found {sorted(documented_operations)}",
    )
    require(
        "variable_conditional_fields",
        "Required for `add`, `subtract`, `multiply`, and `divide`" in variable
        and "`parse_json` requires a non-empty value" in variable
        and "Required for `get` and `stringify`" in variable,
        "document operation-specific value/sourceVariable requirements",
    )

    math_expression = _markdown_section(prompt, "#### mathExpression")
    require(
        "floor_only",
        "sole allowed function `floor(expression)`" in math_expression
        and "Other calls" in math_expression
        and "rejected" in math_expression,
        "floor must be the sole function and other calls must be rejected",
    )

    telegram = _markdown_section(prompt, "#### telegramAlert")
    require(
        "telegram_identity",
        "workflow API key" in telegram
        and "API-key owner" in telegram
        and "cannot supply a\nrecipient override" in telegram
        and "username" not in telegram.lower(),
        "delivery must belong to the API-key owner with no username field",
    )

    http_request = _markdown_section(prompt, "#### httpRequest")
    http_example = _markdown_section(prompt, "### 8.7 Webhook")
    require(
        "http_timeout_range",
        "between 1000 and 60000" in http_request,
        "document the inclusive millisecond timeout range",
    )
    require(
        "http_timeout_example",
        '"timeout": 10000' in http_example,
        "the external HTTP example must use timeout 10000",
    )

    for node_type in ("smartOrder", "basketOrder", "splitOrder"):
        order_section = _markdown_section(prompt, f"#### {node_type}")
        require(
            f"{node_type}_common_prices",
            "`price`" in order_section
            and "`triggerPrice`" in order_section
            and "positive for `LIMIT`/`SL`" in order_section
            and "positive for `SL`/`SL-M`" in order_section,
            "document common price/triggerPrice fields and positive-price rules",
        )

    options_multi = _markdown_section(prompt, "#### optionsMultiOrder")
    require(
        "options_multi_leg_expiry",
        # The node resolves its own expiryType once as the basket default, and a
        # leg may override it with either an exact DDMMMYY date or its own
        # relative type. That is what a calendar or diagonal spread needs, and
        # the doc has to say so - it previously claimed the opposite, which sent
        # anyone wanting one away from a feature that already worked.
        "`expiry`" in options_multi
        and "DDMMMYY" in options_multi
        and "`expiryType`" in options_multi
        and "calendar" in options_multi.lower(),
        "document the per-leg expiry override and the calendar spread it enables",
    )
    require(
        "options_multi_leg_strike",
        "`strikeMode`" in options_multi
        and "`OFFSET`" in options_multi
        and "`STRIKE`" in options_multi
        and "Required unless `strike` is given" in options_multi,
        "document both strike selectors and that exactly one is required",
    )
    require(
        "options_multi_price_types",
        '`priceType` | `"MARKET"` \\| `"LIMIT"`' in options_multi
        and "generated legs do not support `SL`/`SL-M`" in options_multi
        and "a custom leg may use `SL`/`SL-M`" in options_multi,
        "distinguish generated MARKET/LIMIT from custom four-type legs",
    )

    documented_nodes = list(_prompt_json_nodes(prompt))
    telegram_username_examples = [
        (fence_index, start_line, value_index, node.get("id"))
        for fence_index, start_line, value_index, node in documented_nodes
        if node["type"] == "telegramAlert" and "username" in node["data"]
    ]
    require(
        "telegram_json_username",
        not telegram_username_examples,
        "telegramAlert data.username found at "
        f"(fence, start line, value, node): {telegram_username_examples}",
    )

    options_leg_expiry_examples = []
    for fence_index, start_line, value_index, node in documented_nodes:
        if node["type"] != "optionsMultiOrder":
            continue
        for leg_field in ("legs", "orderLegs"):
            if leg_field not in node["data"]:
                continue
            if any(
                isinstance(candidate, dict) and "expiryDate" in candidate
                for candidate in _walk_json(node["data"][leg_field])
            ):
                options_leg_expiry_examples.append(
                    (fence_index, start_line, value_index, node.get("id"), leg_field)
                )
    require(
        "options_multi_json_leg_expiry",
        not options_leg_expiry_examples,
        "optionsMultiOrder leg expiryDate found at "
        f"(fence, start line, value, node, field): {options_leg_expiry_examples}",
    )

    pnl_example = _markdown_section(prompt, "### 8.5 P&L stop-loss")
    require(
        "computed_pnl_condition",
        '"type": "varCondition"' in pnl_example
        and '"type": "priceCondition"' not in pnl_example,
        "computed P&L must be compared with varCondition",
    )

    prohibited_index_orders = [
        (fence_index, start_line, value_index, node.get("id"))
        for fence_index, start_line, value_index, node in documented_nodes
        if node["type"] == "placeOrder"
        and node["data"].get("exchange") in {"NSE_INDEX", "BSE_INDEX"}
    ]
    require(
        "place_order_index_exchange",
        not prohibited_index_orders,
        "placeOrder examples use index exchanges at "
        f"(fence, start line, value, node): {prohibited_index_orders}",
    )

    assert not failures, "prompt prose contract failures:\n" + "\n".join(failures)


def _as_workflow_example(value):
    if isinstance(value, dict) and "nodes" in value and "edges" in value:
        return value

    if isinstance(value, dict):
        snippets = [value]
    elif isinstance(value, list):
        snippets = value
    else:
        return None

    if not snippets or not all(
        isinstance(node, dict)
        and isinstance(node.get("type"), str)
        and isinstance(node.get("data"), dict)
        for node in snippets
    ):
        return None

    nodes = []
    for index, snippet in enumerate(snippets, 1):
        node = dict(snippet)
        node.setdefault("id", f"documented_node_{index}")
        node.setdefault("position", {"x": 100, "y": index * 100})
        nodes.append(node)

    trigger_ids = [node["id"] for node in nodes if node["type"] in TRIGGER_NODE_TYPES]
    if not trigger_ids:
        nodes.insert(0, _node("documented_trigger", "start"))
        trigger_ids = ["documented_trigger"]
    if len(nodes) == 1:
        nodes.append(_node("documented_action", "log", message="Prompt contract example"))

    trigger_id = trigger_ids[0]
    edges = [
        {"id": f"documented_edge_{index}", "source": trigger_id, "target": node["id"]}
        for index, node in enumerate(nodes, 1)
        if node["id"] != trigger_id
    ]
    return _wf(nodes, edges, name="Prompt contract example")


def test_every_parseable_prompt_json_example_matches_the_strict_contract():
    """Malformed or runtime-invalid prompt JSON must identify its source fence."""
    prompt = FLOW_IMPORT_PROMPT.read_text(encoding="utf-8")
    failures = []
    fence_lines = {}
    seen_multi_value_fences = {}

    for index, line, raw in _json_fences(prompt):
        fence_lines[index] = line
        try:
            values = [json.loads(raw)]
        except json.JSONDecodeError:
            try:
                values = _decode_json_sequence(raw)
            except json.JSONDecodeError as exc:
                failures.append((index, line, [{"code": "invalid_json", "message": str(exc)}]))
                continue

            expected_count = MULTI_VALUE_JSON_FENCES.get(index)
            if expected_count != len(values):
                failures.append(
                    (
                        index,
                        line,
                        [
                            {
                                "code": "unexpected_json_sequence",
                                "message": f"decoded {len(values)} values; expected {expected_count or 1}",
                            }
                        ],
                    )
                )
                continue
            seen_multi_value_fences[index] = len(values)

        for value in values:
            payload = _as_workflow_example(value)
            if payload is None:
                continue
            errors = validate_workflow(payload, strict=True)
            if errors:
                failures.append((index, line, errors))

    for index, expected_count in MULTI_VALUE_JSON_FENCES.items():
        if index not in seen_multi_value_fences:
            failures.append(
                (
                    index,
                    fence_lines.get(index),
                    [
                        {
                            "code": "missing_json_sequence",
                            "message": f"expected the allowlisted sequence of {expected_count} values",
                        }
                    ],
                )
            )

    assert failures == []
    assert seen_multi_value_fences == MULTI_VALUE_JSON_FENCES


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


PRICED_ORDER_NODES = {
    "placeOrder": {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1},
    "smartOrder": {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1},
    "optionsOrder": {"underlying": "NIFTY", "action": "BUY", "quantity": 1},
    "optionsMultiOrder": {"strategy": "straddle", "underlying": "NIFTY", "quantity": 1},
    "basketOrder": {"orders": "RELIANCE,NSE,BUY,1"},
    "splitOrder": {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "splitSize": 1,
    },
}


@pytest.mark.parametrize("node_type,minimal", PRICED_ORDER_NODES.items())
@pytest.mark.parametrize(
    ("price_type", "required_field"),
    [("LIMIT", "price"), ("SL", "price"), ("SL", "triggerPrice"), ("SL-M", "triggerPrice")],
)
def test_priced_order_requires_each_static_price(node_type, minimal, price_type, required_field):
    """A priced executable order cannot rely on the broker's zero default."""
    data = {**minimal, "priceType": price_type}
    errors = _strict_node_errors(node_type, data)
    assert any(
        error["code"] == "missing_price" and error["path"].endswith(f"/{required_field}")
        for error in errors
    )
    assert not any(
        error["path"].endswith(f"/{required_field}")
        for error in _permissive_node_errors(node_type, data)
    )


@pytest.mark.parametrize("node_type,minimal", PRICED_ORDER_NODES.items())
@pytest.mark.parametrize(
    ("price_type", "required_field"),
    [("LIMIT", "price"), ("SL", "price"), ("SL", "triggerPrice"), ("SL-M", "triggerPrice")],
)
@pytest.mark.parametrize(
    ("value", "strict_code", "permissive_code"),
    [
        ("", "missing_price", None),
        (0, "invalid_price", "invalid_price"),
        (-1, "invalid_price", "invalid_price"),
        (1, None, None),
        ("{{webhook.price}}", None, None),
    ],
)
def test_priced_order_price_values_follow_draft_and_runtime_contract(
    node_type, minimal, price_type, required_field, value, strict_code, permissive_code
):
    """Blank values are incomplete drafts; supplied malformed prices are always invalid."""
    data = {**minimal, "priceType": price_type, required_field: value}
    strict_errors = _strict_node_errors(node_type, data)
    permissive_errors = _permissive_node_errors(node_type, data)
    assert any(
        error["code"] == strict_code and error["path"].endswith(f"/{required_field}")
        for error in strict_errors
    ) is (strict_code is not None)
    assert any(
        error["code"] == permissive_code and error["path"].endswith(f"/{required_field}")
        for error in permissive_errors
    ) is (permissive_code is not None)


MARGIN_LEG = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": "1",
    "product": "MIS",
    "pricetype": "MARKET",
    "price": "0",
}


@pytest.mark.parametrize(
    ("data", "strict_code", "permissive_code", "path"),
    [
        ({}, "missing_alternative", None, "positionsJson"),
        ({"positionsJson": ""}, "missing_alternative", None, "positionsJson"),
        ({"positionsJson": "not json"}, "invalid_positions", "invalid_positions", "positionsJson"),
        ({"positionsJson": "[]"}, "invalid_positions", "invalid_positions", "positionsJson"),
        ({"positionsJson": "{}"}, "invalid_positions", "invalid_positions", "positionsJson"),
        ({"positionsJson": '["not a leg"]'}, "invalid_positions", "invalid_positions", "positionsJson/0"),
        (
            {"positionsJson": '[{"symbol": "RELIANCE"}]'},
            "missing_required_field",
            None,
            "positionsJson/0/exchange",
        ),
        (
            {"positionsJson": '[{"symbol": "RELIANCE", "exchange": "NOPE", "action": "BUY", "quantity": "1", "product": "MIS", "pricetype": "MARKET", "price": "0"}]'},
            "invalid_constant",
            "invalid_constant",
            "positionsJson/0/exchange",
        ),
        (
            {"positionsJson": '[{"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": "1", "product": "MIS", "pricetype": "LIMIT", "price": "0"}]'},
            "invalid_price",
            "invalid_price",
            "positionsJson/0/price",
        ),
        ({"positionsJson": "{{webhook.positions}}"}, None, None, "positionsJson"),
        (
            {"positionsJson": '[{"symbol": "{{symbol}}", "exchange": "NSE", "action": "BUY", "quantity": "{{quantity}}", "product": "MIS", "pricetype": "LIMIT", "price": "{{price}}"}]'},
            None,
            None,
            "positionsJson",
        ),
        ({"positionsJson": '[{"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": "1", "product": "MIS", "pricetype": "MARKET", "price": "0"}]'}, None, None, "positionsJson"),
        ({"positions": [MARGIN_LEG]}, None, None, "positions"),
        ({"symbol": "RELIANCE"}, None, None, "symbol"),
    ],
)
def test_margin_contract(data, strict_code, permissive_code, path):
    """Margin either prices one legacy symbol or a complete, static basket."""
    strict_errors = _strict_node_errors("margin", data)
    permissive_errors = _permissive_node_errors("margin", data)
    assert any(
        error["code"] == strict_code and error["path"].endswith(f"/{path}")
        for error in strict_errors
    ) is (strict_code is not None)
    assert any(
        error["code"] == permissive_code and error["path"].endswith(f"/{path}")
        for error in permissive_errors
    ) is (permissive_code is not None)


OPTIONS_MULTI_BASE = {"underlying": "NIFTY", "quantity": 1}
CUSTOM_OPTION_LEG = {
    "offset": "ATM",
    "optionType": "CE",
    "action": "BUY",
    "quantity": 1,
}


@pytest.mark.parametrize(
    ("data", "strict_code", "permissive_code", "path"),
    [
        ({**OPTIONS_MULTI_BASE, "strategy": "custom"}, "missing_required_field", None, "legs"),
        ({**OPTIONS_MULTI_BASE, "strategy": "custom", "legs": []}, "invalid_legs", "invalid_legs", "legs"),
        ({**OPTIONS_MULTI_BASE, "strategy": "custom", "legs": {}}, "invalid_legs", "invalid_legs", "legs"),
        (
            {**OPTIONS_MULTI_BASE, "strategy": "custom", "legs": [{"offset": "ATM"}]},
            "missing_required_field",
            None,
            "legs/0/optionType",
        ),
        (
            {
                **OPTIONS_MULTI_BASE,
                "strategy": "custom",
                "legs": [{**CUSTOM_OPTION_LEG, "product": "NOPE"}],
            },
            "invalid_constant",
            "invalid_constant",
            "legs/0/product",
        ),
        (
            {
                **OPTIONS_MULTI_BASE,
                "strategy": "custom",
                "legs": [
                    {
                        **CUSTOM_OPTION_LEG,
                        "priceType": "SL",
                        "price": 100,
                        "triggerPrice": 99,
                        "expiryDate": "27AUG26",
                    }
                ],
            },
            None,
            None,
            "legs",
        ),
        (
            {
                **OPTIONS_MULTI_BASE,
                "strategy": "custom",
                "legs": [
                    {
                        "offset": "{{offset}}",
                        "optionType": "{{optionType}}",
                        "action": "{{action}}",
                        "quantity": "{{quantity}}",
                        "priceType": "{{priceType}}",
                        "price": "{{price}}",
                    }
                ],
            },
            None,
            None,
            "legs",
        ),
        (
            {**OPTIONS_MULTI_BASE, "strategy": "custom", "legs": "{{webhook.legs}}"},
            None,
            None,
            "legs",
        ),
        (
            {**OPTIONS_MULTI_BASE, "strategy": "straddle", "priceType": "SL", "price": 100},
            "invalid_constant",
            "invalid_constant",
            "priceType",
        ),
        ({**OPTIONS_MULTI_BASE, "strategy": "straddle", "priceType": "MARKET"}, None, None, "price"),
        (
            {**OPTIONS_MULTI_BASE, "strategy": "straddle", "priceType": "LIMIT", "price": 100},
            None,
            None,
            "price",
        ),
    ],
)
def test_options_multi_contract(data, strict_code, permissive_code, path):
    """Custom strategies validate each leg; generated strategies support MARKET and LIMIT only."""
    strict_errors = _strict_node_errors("optionsMultiOrder", data)
    permissive_errors = _permissive_node_errors("optionsMultiOrder", data)
    assert any(
        error["code"] == strict_code and error["path"].endswith(f"/{path}")
        for error in strict_errors
    ) is (strict_code is not None)
    assert any(
        error["code"] == permissive_code and error["path"].endswith(f"/{path}")
        for error in permissive_errors
    ) is (permissive_code is not None)


@pytest.mark.parametrize(
    ("operation", "extra"),
    [
        ("set", {}),
        ("get", {"sourceVariable": "source"}),
        ("add", {"value": 1}),
        ("subtract", {"value": 1}),
        ("multiply", {"value": 2}),
        ("divide", {"value": 2}),
        ("increment", {}),
        ("decrement", {}),
        ("parse_json", {"value": '{"key": "value"}'}),
        ("stringify", {"sourceVariable": "source"}),
        ("append", {}),
    ],
)
def test_variable_contract_accepts_supported_operations(operation, extra):
    """Every executor operation has a configuration shape that can activate."""
    data = {"variableName": "target", "operation": operation, **extra}
    for errors in (_strict_node_errors("variable", data), _permissive_node_errors("variable", data)):
        assert not any(
            error["path"].endswith(("/operation", "/sourceVariable", "/value"))
            for error in errors
        )


def test_variable_contract_rejects_unknown_operations_even_in_drafts():
    """A saved operation typo cannot silently fall through the executor."""
    data = {"variableName": "target", "operation": "merge"}
    for errors in (_strict_node_errors("variable", data), _permissive_node_errors("variable", data)):
        assert any(error["code"] == "invalid_constant" and error["path"].endswith("/operation") for error in errors)


@pytest.mark.parametrize("operation,field", [("get", "sourceVariable"), ("stringify", "sourceVariable")])
def test_variable_contract_requires_a_source_variable_in_strict_mode(operation, field):
    """Read-based operations need the source name once the workflow is executable."""
    data = {"variableName": "target", "operation": operation}
    assert any(error["code"] == "missing_required_field" and error["path"].endswith(f"/{field}") for error in _strict_node_errors("variable", data))
    assert not any(error["path"].endswith(f"/{field}") for error in _permissive_node_errors("variable", data))


@pytest.mark.parametrize("operation", ["add", "subtract", "multiply", "divide", "parse_json"])
def test_variable_contract_requires_a_value_in_strict_mode(operation):
    """Operations that consume an operand cannot use the executor's empty default."""
    data = {"variableName": "target", "operation": operation}
    assert any(error["code"] == "missing_required_field" and error["path"].endswith("/value") for error in _strict_node_errors("variable", data))
    assert not any(error["path"].endswith("/value") for error in _permissive_node_errors("variable", data))


@pytest.mark.parametrize(("operation", "field"), [("get", "sourceVariable"), ("add", "value")])
def test_variable_contract_defers_templated_conditional_values(operation, field):
    """Template references are supplied values whose resolution belongs to runtime."""
    errors = _strict_node_errors(
        "variable", {"variableName": "target", "operation": operation, field: "{{webhook.value}}"}
    )
    assert not any(error["path"].endswith(f"/{field}") for error in errors)


def test_variable_contract_defaults_a_missing_operation_to_set():
    """Legacy Variable nodes did not persist their default operation."""
    errors = _strict_node_errors("variable", {"variableName": "target"})
    assert not any(error["path"].endswith("/operation") for error in errors)


@pytest.mark.parametrize("operation", ["", "SET", " set "])
def test_variable_contract_rejects_noncanonical_operation_spellings(operation):
    """Only the executor's exact lowercase operation names are executable."""
    data = {"variableName": "target", "operation": operation}
    for errors in (_strict_node_errors("variable", data), _permissive_node_errors("variable", data)):
        assert any(
            error["code"] == "invalid_constant" and error["path"].endswith("/operation")
            for error in errors
        )


@pytest.mark.parametrize("value", [True, float("inf"), float("-inf"), "Infinity", "-Infinity", "NaN"])
def test_executable_price_rejects_boolean_and_nonfinite_values(value):
    """Broker prices must be finite numbers, never truthy or infinite floats."""
    data = {**PRICED_ORDER_NODES["placeOrder"], "priceType": "LIMIT", "price": value}
    for errors in (_strict_node_errors("placeOrder", data), _permissive_node_errors("placeOrder", data)):
        assert any(error["code"] == "invalid_price" and error["path"].endswith("/price") for error in errors)


@pytest.mark.parametrize("value", [True, float("inf"), float("-inf"), "Infinity", "-Infinity", "NaN"])
def test_custom_option_leg_quantity_rejects_boolean_and_nonfinite_values(value):
    """A custom leg quantity uses the same finite-number contract as an order."""
    data = {
        **OPTIONS_MULTI_BASE,
        "strategy": "custom",
        "legs": [{**CUSTOM_OPTION_LEG, "quantity": value}],
    }
    for errors in (
        _strict_node_errors("optionsMultiOrder", data),
        _permissive_node_errors("optionsMultiOrder", data),
    ):
        assert any(
            error["code"] == "invalid_quantity" and error["path"].endswith("/legs/0/quantity")
            for error in errors
        )


@pytest.mark.parametrize("value", [1, "1.25"])
def test_executable_price_and_custom_leg_quantity_keep_finite_values(value):
    """Finite numeric values remain valid in both shared numeric helpers."""
    price_data = {**PRICED_ORDER_NODES["placeOrder"], "priceType": "LIMIT", "price": value}
    leg_data = {
        **OPTIONS_MULTI_BASE,
        "strategy": "custom",
        "legs": [{**CUSTOM_OPTION_LEG, "quantity": value}],
    }
    for errors in (_strict_node_errors("placeOrder", price_data), _permissive_node_errors("placeOrder", price_data)):
        assert not any(error["path"].endswith("/price") for error in errors)
    for errors in (
        _strict_node_errors("optionsMultiOrder", leg_data),
        _permissive_node_errors("optionsMultiOrder", leg_data),
    ):
        assert not any(error["path"].endswith("/legs/0/quantity") for error in errors)


@pytest.mark.parametrize("positions_json", ["{{webhook.positions}}", "[{{webhook.positions}}]"])
def test_margin_contract_defers_any_template_containing_positions_json(positions_json):
    """A templated Margin basket is resolved at runtime before JSON parsing."""
    data = {"positionsJson": positions_json}
    for errors in (_strict_node_errors("margin", data), _permissive_node_errors("margin", data)):
        assert not any(error["path"].endswith("/positionsJson") for error in errors)


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
