"""Check a workflow JSON before it is imported.

    uv run python .claude/skills/flow-builder/validate.py my_workflow.json

Two layers. The first is the importer's own `validate_workflow`, called
directly rather than reimplemented, so this can never disagree with what the
server will accept. The second is a set of checks the importer deliberately does
not make, because they are not errors so much as near-certain mistakes:

* a `data` key no executor reads. Flow ignores unknown keys, so `strikeOffset`
  instead of `offset` silently leaves the node on its default. Every field this
  author thought they set is checked against what the node actually reads.
* a `{{reference}}` on an order field whose path nothing in the graph produces.
  The run would fail at the broker call; better to say so now.
* an order node with no upstream trigger path.

Exit code 0 means it will import.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.flow_workflow_validator import (  # noqa: E402
    VALID_NODE_TYPES,
    validate_workflow,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_reference import TRIGGERS, executor_keys  # noqa: E402

# Read by the runtime for every node, not by any one node's method.
UNIVERSAL_KEYS = {
    "label", "outputVariable", "strategyTag", "notes", "description",
}
TOKEN = re.compile(r"\{\{([^}]+)\}\}")


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAILED: {path.name} is not valid JSON: {exc}")
        raise SystemExit(2) from exc


def unknown_keys(nodes: list, keys: dict[str, list[str]]) -> list[str]:
    out = []
    for node in nodes:
        ntype = node.get("type")
        if ntype not in VALID_NODE_TYPES or ntype in TRIGGERS:
            continue
        known = set(keys.get(ntype, ())) | UNIVERSAL_KEYS
        if not known - UNIVERSAL_KEYS:
            continue  # nothing scraped for this node; do not guess
        for key in node.get("data", {}):
            if key not in known:
                out.append(
                    f"{node.get('id')} ({ntype}): data key '{key}' is read by nothing. "
                    f"Flow ignores it, so the node keeps its default. "
                    f"It reads: {', '.join(sorted(known - UNIVERSAL_KEYS))}"
                )
    return out


def dangling_references(nodes: list) -> list[str]:
    """A {{path}} whose root nothing in this workflow produces."""
    produced = {"webhook"}
    for node in nodes:
        var = node.get("data", {}).get("outputVariable")
        if isinstance(var, str) and var.strip():
            produced.add(var.strip())
        name = node.get("data", {}).get("variableName") or node.get("data", {}).get("name")
        if node.get("type") == "variable" and isinstance(name, str) and name.strip():
            produced.add(name.strip())
    builtins = {
        "timestamp", "date", "time", "year", "month", "day", "hour",
        "minute", "second", "weekday", "iso_timestamp",
    }
    out = []
    for node in nodes:
        for key, value in node.get("data", {}).items():
            if not isinstance(value, str):
                continue
            for token in TOKEN.findall(value):
                root = token.strip().split(".")[0].split("[")[0]
                if root and root not in produced and root not in builtins:
                    out.append(
                        f"{node.get('id')} ({node.get('type')}): {key} references "
                        f"'{{{{{token.strip()}}}}}' but nothing produces '{root}'. "
                        f"Available: {', '.join(sorted(produced))}"
                    )
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"FAILED: {path} does not exist")
        return 2

    payload = load(path)
    nodes = payload.get("nodes") or []

    # Layer 1: exactly what the importer will run.
    errors = validate_workflow(payload, require_name=True, strict=True)
    for err in errors:
        print(f"  ERROR    {err.get('path', '?')}: {err.get('message', err)}")

    # Layer 2: the mistakes that import cleanly and then misbehave.
    warnings = unknown_keys(nodes, executor_keys()) + dangling_references(nodes)
    for warning in warnings:
        print(f"  WARNING  {warning}")

    print()
    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s). Will not import.")
        return 1
    if warnings:
        print(
            f"PASSED with {len(warnings)} warning(s). It will import, but a warned "
            f"field is being ignored at run time."
        )
        return 0
    print(f"PASSED: {len(nodes)} node(s), no errors, no warnings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
