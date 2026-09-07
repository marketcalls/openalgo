"""Regenerate reference/nodes.md from the code that actually runs.

Every fact in the node reference is read out of the validator and the executor
rather than typed, so the reference cannot drift from the contract the way a
hand-maintained table does. Run this after changing a node's fields.

    uv run python .claude/skills/flow-builder/generate_reference.py
"""

import re
import sys
from pathlib import Path

# Run from anywhere: the repo root has to be importable for `services.*`.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.flow_node_contracts import (  # noqa: E402
    VALID_EXPIRY_TYPES,
    VALID_LEG_STRIKE_MODES,
)
from services.flow_workflow_validator import (  # noqa: E402
    REQUIRED_NODE_FIELDS,
    VALID_ACTIONS,
    VALID_EXCHANGES,
    VALID_NODE_TYPES,
    VALID_OPTION_TYPES,
    VALID_PRICE_TYPES,
    VALID_PRODUCTS,
)

EXECUTOR = ROOT / "services" / "flow_executor_service.py"
OUT = Path(__file__).resolve().parent / "reference" / "nodes.md"

TRIGGERS = {"start", "webhookTrigger", "priceAlert", "orderUpdateTrigger"}
BRANCHING = {
    "priceCondition", "timeCondition", "timeWindow", "positionCheck",
    "fundCheck", "varCondition",
}
GATES = {"andGate", "orGate"}
# Reaches a broker with an order. Every field on these is guarded: an
# unresolved reference fails the node rather than becoming a default.
ORDER_NODES = {
    "placeOrder", "smartOrder", "splitOrder", "basketOrder",
    "optionsOrder", "optionsMultiOrder", "modifyOrder", "cancelOrder",
    "cancelAllOrders", "closePositions",
}


def executor_keys() -> dict[str, list[str]]:
    """Which `data` keys each node's executor actually reads."""
    src = EXECUTOR.read_text(encoding="utf-8")
    dispatch = dict(
        re.findall(r'node_type == "([a-zA-Z]+)":\s*\n\s*result = executor\.(\w+)\(', src)
    )
    lines = src.split("\n")
    starts = [
        (i, m.group(1))
        for i, line in enumerate(lines)
        if (m := re.match(r"    def (\w+)\(", line))
    ]
    bodies: dict[str, str] = {}
    for idx, (i, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        bodies[name] = "\n".join(lines[i:end])

    def keys_in(body: str) -> set[str]:
        return set(
            re.findall(r'get_(?:str|int|float|bool)\(\s*node_data,\s*"([a-zA-Z_]+)"', body)
            + re.findall(r'node_data\.get\(\s*"([a-zA-Z_]+)"', body)
            + re.findall(r'values\.(?:text|enum|integer|number)\(\s*"([a-zA-Z_]+)"', body)
            # A key handed to a helper as an argument rather than read inline:
            # `self._operand(node_data, "leftValue")`. varCondition reads both
            # of its operands this way and nothing else, so without this the
            # node appeared to read only its operator.
            + re.findall(r'self\.\w+\(\s*node_data,\s*"([a-zA-Z_]+)"', body)
        )

    out: dict[str, list[str]] = {}
    for node, method in dispatch.items():
        body = bodies.get(method, "")
        keys = keys_in(body)
        # Follow the helpers the method delegates to. Several order nodes read
        # almost nothing directly: placeOrder, smartOrder and splitOrder all
        # hand `node_data` to `resolve_standard_order`, so scanning only the
        # method body reported action, quantity, product and priceType as read
        # by nothing -- which is the exact warning this reference exists to make
        # trustworthy. One level is enough for every node here.
        for helper in set(re.findall(r'self\.(\w+)\(\s*node_data', body)):
            keys |= keys_in(bodies.get(helper, ""))
        out[node] = sorted(keys)
    return out


def kind(node: str) -> str:
    if node in TRIGGERS:
        return "trigger"
    if node in GATES:
        return "gate"
    if node in BRANCHING:
        return "condition"
    if node in ORDER_NODES:
        return "order"
    return "action"


def main() -> None:
    keys = executor_keys()
    missing_from_executor = sorted(VALID_NODE_TYPES - set(keys) - TRIGGERS - GATES)

    rows = []
    for node in sorted(VALID_NODE_TYPES):
        required = ", ".join(f"`{f}`" for f in REQUIRED_NODE_FIELDS.get(node, ())) or "none"
        read = keys.get(node, [])
        optional = [k for k in read if k not in REQUIRED_NODE_FIELDS.get(node, ())]
        rows.append(
            f"| `{node}` | {kind(node)} | {required} | "
            f"{', '.join(f'`{k}`' for k in optional) or '-'} |"
        )

    body = f"""# Flow node reference

Generated from `services/flow_workflow_validator.py` and
`services/flow_executor_service.py` by `generate_reference.py`. Do not hand-edit:
regenerate it instead, so the table cannot drift from the contract.

**{len(VALID_NODE_TYPES)} node types.** `Required` is what strict validation
demands at import and activation. `Also read` is every other `data` key the
executor looks at, so it is the complete set of what a node responds to.

## Every node

| Type | Kind | Required | Also read |
|---|---|---|---|
{chr(10).join(rows)}

## Enumerated values

Matching is case-insensitive: a payload sending `buy` is accepted for `BUY`.

| Field | Accepted |
|---|---|
| `action` | {', '.join(f'`{v}`' for v in sorted(VALID_ACTIONS))} |
| `exchange` | {', '.join(f'`{v}`' for v in sorted(VALID_EXCHANGES))} |
| `product` | {', '.join(f'`{v}`' for v in sorted(VALID_PRODUCTS))} |
| `priceType` | {', '.join(f'`{v}`' for v in sorted(VALID_PRICE_TYPES))} |
| `optionType` | {', '.join(f'`{v}`' for v in sorted(VALID_OPTION_TYPES))} |
| `expiryType` | {', '.join(f'`{v}`' for v in sorted(VALID_EXPIRY_TYPES))}, or a `DDMMMYY` date |
| leg `strikeMode` | {', '.join(f'`{v}`' for v in sorted(VALID_LEG_STRIKE_MODES))} |
| `offset` | `ATM`, `ITM1`-`ITM50`, `OTM1`-`OTM50` |

## Kinds

- **trigger** ({', '.join(f'`{t}`' for t in sorted(TRIGGERS))}) - a workflow needs
  exactly one, and it is the single execution root.
- **condition** - fans out into TRUE and FALSE branches; edges leaving one must
  set `sourceHandle`.
- **gate** - waits for every wired input before firing once.
- **order** - reaches a broker. Every field is guarded, so an unresolved
  `{{{{reference}}}}` fails the node instead of becoming a default.
- **action** - everything else: data, utility, streaming.

## Nodes with no executor branch

{', '.join(f'`{n}`' for n in missing_from_executor) or 'None.'}

These are handled inline or by the graph walk rather than by a node method.
"""
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} covering {len(VALID_NODE_TYPES)} node types")


if __name__ == "__main__":
    main()
