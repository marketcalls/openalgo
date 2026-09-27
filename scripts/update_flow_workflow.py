# scripts/update_flow_workflow.py
"""Update an existing Flow workflow from a JSON file, in place.

Importing a JSON always creates a *new* workflow, so iterating on a strategy
leaves a trail of copies and, worse, a new webhook URL each time. This replaces
the graph of a workflow you already have, keeping its id, webhook token and
secret, API key, and active state.

    # see what you have
    uv run python scripts/update_flow_workflow.py --list

    # replace workflow 3's graph with a new JSON
    uv run python scripts/update_flow_workflow.py --id 3 --file strategy.json

    # check what would change without writing
    uv run python scripts/update_flow_workflow.py --id 3 --file strategy.json --dry-run

The graph is re-read from the database on every run, so a workflow that is
already active picks up the new nodes on its next tick. The one exception is
the trigger itself: its schedule and any price/order watch are registered at
activation, so changing any part of the trigger's configuration needs a
deactivate/reactivate cycle. This script reports when that applies.

Output note: this is an operator-facing CLI, so results go to stdout via
print() rather than the application logger - the output *is* the product here,
and it must be readable when run outside the app. Application code continues to
use utils.logging.get_logger.
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")

from database.flow_db import get_all_workflows, get_workflow, update_workflow  # noqa: E402
from services.flow_workflow_validator import (  # noqa: E402
    migrate_legacy_node_data,
    trigger_config,
    validate_workflow,
)

# Trigger comparison lives with the validator so this script, the replace
# endpoint and the audit all answer "does this need a reactivate" the same way.
_trigger_config = trigger_config


def show_list() -> int:
    workflows = get_all_workflows() or []
    if not workflows:
        print("No workflows found.")
        return 0
    print(f"{'ID':>4}  {'ACTIVE':7}  {'NODES':>5}  NAME")
    for wf in workflows:
        nodes = len(wf.nodes or [])
        print(f"{wf.id:>4}  {'yes' if wf.is_active else 'no':7}  {nodes:>5}  {wf.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list workflows and exit")
    parser.add_argument("--id", type=int, help="workflow id to update")
    parser.add_argument("--file", help="path to the updated workflow JSON")
    parser.add_argument("--name", help="also rename the workflow")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and report, but do not write"
    )
    args = parser.parse_args()

    if args.list:
        return show_list()
    if args.id is None or not args.file:
        parser.error("--id and --file are required (or use --list)")

    workflow = get_workflow(args.id)
    if not workflow:
        print(f"No workflow with id {args.id}. Use --list to see what exists.")
        return 1

    try:
        payload = json.loads(pathlib.Path(args.file).read_text())
    except (OSError, ValueError) as exc:
        print(f"Could not read {args.file}: {exc}")
        return 1

    # Same normalization the import endpoint applies, so a legacy export does
    # not arrive here still carrying a field no reader honors.
    migration_notes: list[str] = []
    if isinstance(payload.get("nodes"), list):
        payload["nodes"], migration_notes = migrate_legacy_node_data(payload["nodes"])

    # Same rules the import endpoint applies, so a graph that would be rejected
    # at import is not written here through the side door.
    errors = validate_workflow(payload)
    if errors:
        print(f"{args.file} is not a valid workflow:\n")
        for err in errors:
            print(f"  {err['path']}: {err['message']}")
        return 1

    # Captured before the write. Reading workflow.nodes afterwards can return
    # the refreshed row, so the comparison would be against the new graph.
    old_trigger = _trigger_config(workflow.nodes or [])
    new_trigger = _trigger_config(payload["nodes"])

    old_nodes = len(workflow.nodes or [])
    old_edges = len(workflow.edges or [])
    new_nodes = len(payload.get("nodes") or [])
    new_edges = len(payload.get("edges") or [])

    print(f"Workflow {workflow.id}: {workflow.name}")
    print(f"  active      : {'yes' if workflow.is_active else 'no'}")
    print(f"  nodes       : {old_nodes} -> {new_nodes}")
    print(f"  edges       : {old_edges} -> {new_edges}")
    if args.name:
        print(f"  name        : {workflow.name} -> {args.name}")
    print("  webhook url : unchanged")
    if migration_notes:
        print("  migrations  :")
        for note in migration_notes:
            print(f"    - {note}")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    fields = {"nodes": payload["nodes"], "edges": payload["edges"]}
    if args.name:
        fields["name"] = args.name

    if not update_workflow(args.id, **fields):
        print("\nUpdate failed.")
        return 1

    print("\nUpdated.")
    if workflow.is_active:
        if old_trigger != new_trigger:
            print(
                "The trigger configuration changed and this workflow is active.\n"
                f"  was: {old_trigger}\n"
                f"  now: {new_trigger}\n"
                "Deactivate and reactivate it: the schedule and any price/order "
                "watch are registered at activation, not read per run."
            )
        else:
            print("Active workflow: the new graph applies from the next run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
