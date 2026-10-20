"""Is every node type the server accepts actually documented?

    uv run python .claude/skills/flow-builder/coverage.py

Three checks, because "documented" can mean three different things and only the
last one is worth anything to whoever reads the skill:

  LISTED        the type appears in reference/nodes.md
  FIELDED       its required fields are stated there
  EXPLAINED     it appears in docs/prompt/flow-import-format.md, which is where
                the semantics live rather than the field names

A type the server accepts but nothing describes is worse than a missing one: an
agent will invent fields for it, and Flow ignores keys nothing reads, so the
workflow imports and quietly does the wrong thing.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from services.flow_workflow_validator import (  # noqa: E402
    REQUIRED_NODE_FIELDS,
    VALID_NODE_TYPES,
)

REFERENCE = Path(__file__).resolve().parent / "reference" / "nodes.md"
LONG_FORM = ROOT / "docs" / "prompt" / "flow-import-format.md"


def main() -> int:
    reference = REFERENCE.read_text(encoding="utf-8") if REFERENCE.exists() else ""
    long_form = LONG_FORM.read_text(encoding="utf-8") if LONG_FORM.exists() else ""

    listed, fielded, explained = [], [], []
    for node in sorted(VALID_NODE_TYPES):
        if f"`{node}`" not in reference:
            listed.append(node)
            continue
        required = REQUIRED_NODE_FIELDS.get(node, ())
        if required and not all(f"`{f}`" in reference for f in required):
            fielded.append(node)
        if node not in long_form:
            explained.append(node)

    total = len(VALID_NODE_TYPES)
    for label, gaps in (
        ("listed in the reference", listed),
        ("required fields stated", fielded),
        ("explained in the long form", explained),
    ):
        print(f"  {label:28s} {total - len(gaps):3d}/{total}")
        if gaps:
            print(f"      missing: {', '.join(gaps)}")

    failures = len(listed) + len(fielded) + len(explained)
    print()
    if failures:
        print(f"GAPS: {failures}. Regenerate with generate_reference.py, or write the missing prose.")
        return 1
    print(f"COVERAGE COMPLETE: {total}/{total} node types on all three checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
