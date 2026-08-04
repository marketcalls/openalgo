"""Explain why a Flow workflow is not placing orders.

Checks every gate an order has to pass and prints the ones that are shut. Run
it on the machine that is not trading:

    uv run python scripts/flow_diagnose.py 107

Read-only: it never executes the workflow and never places an order.

Deliberately does not import ``app.py``. Importing that starts the WebSocket
proxy and the schedulers as a side effect, which on a live machine either
fights the running instance for port 8765 or brings up a second copy of the
trading stack. The database layer is plain SQLAlchemy with its own
``scoped_session``, so loading ``.env`` is all this needs.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, time

# Runnable from anywhere, including scripts/ itself.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse(value: str, default: time) -> time:
    try:
        parts = [int(p) for p in str(value).split(":")]
        return time(*parts[:3])
    except (TypeError, ValueError):
        return default


def diagnose(workflow_id: int) -> int:
    from dotenv import load_dotenv

    load_dotenv()

    import pytz

    from database.flow_db import get_workflow, get_workflow_api_key
    from database.settings_db import get_analyze_mode
    from services.flow_workflow_validator import validate_workflow

    wf = get_workflow(workflow_id)
    if not wf:
        print(f"No workflow with id {workflow_id}.")
        return 1

    print(f"Workflow {workflow_id}: {wf.name}\n")
    blockers: list[str] = []

    # 1. Clock. The scheduler's market-hours gate is IST-aware, but timeWindow
    # nodes compare against the server's local clock, so a host that is not on
    # IST evaluates every window in the wrong timezone.
    local = datetime.now()
    ist = datetime.now(pytz.timezone("Asia/Kolkata"))
    skew = round(
        (local.replace(tzinfo=None) - ist.replace(tzinfo=None)).total_seconds() / 60
    )
    print(f"  server local time : {local.strftime('%Y-%m-%d %H:%M')}")
    print(f"  IST               : {ist.strftime('%Y-%m-%d %H:%M')}")
    if abs(skew) > 1:
        print(f"  MISMATCH          : local clock is {skew:+d} min from IST")
        blockers.append(
            f"Server timezone is not IST ({skew:+d} min). timeWindow nodes use the "
            "server's local clock, so IST windows are compared against the wrong "
            "time. Set TZ=Asia/Kolkata (the official Docker image already does)."
        )
    else:
        print("  timezone          : IST, correct")

    # 2. Activation.
    print(f"\n  is_active         : {bool(wf.is_active)}")
    print(f"  schedule job      : {wf.schedule_job_id}")
    print(f"  webhook enabled   : {bool(wf.webhook_enabled)}")
    if not wf.is_active:
        blockers.append(
            "Workflow is not activated, so nothing triggers it. Activate it in the "
            "editor."
        )
    elif not wf.schedule_job_id and not wf.webhook_enabled:
        blockers.append(
            "Active but has no schedule job and no webhook, so no trigger reaches it. "
            "Deactivate and reactivate to re-register the schedule."
        )

    # 3. Credentials.
    api_key = get_workflow_api_key(wf)
    print(f"  api key stored    : {bool(api_key)}")
    if not api_key:
        blockers.append(
            "No API key stored on the workflow. Reactivate it while logged in so the "
            "key is captured."
        )

    # 4. Graph completeness - the same strict check activation and every trigger
    # path applies before touching the broker.
    errors = validate_workflow(
        {"name": wf.name, "nodes": wf.nodes or [], "edges": wf.edges or []},
        strict=True,
    )
    print(f"  graph validation  : {'clean' if not errors else errors[0]['message']}")
    if errors:
        blockers.append(f"Graph is not runnable: {errors[0]['message']}")

    # 5. Where orders would actually go.
    if get_analyze_mode():
        print("  analyzer mode     : ON - orders are simulated")
        blockers.append(
            "Analyzer mode is ON, so orders are simulated into the analyzer and never "
            "reach the broker. Turn it off to trade live."
        )
    else:
        print("  analyzer mode     : off - orders go to the broker")

    # 6. Time windows, against the clock the executor will actually use.
    windows = [
        (n.get("id"), (n.get("data") or {}))
        for n in (wf.nodes or [])
        if n.get("type") == "timeWindow"
    ]
    if windows:
        now_t = local.time()
        print("\n  time windows (vs server local clock):")
        open_any = False
        for nid, data in windows:
            start = _parse(data.get("startTime", "00:00"), time(0, 0))
            end = _parse(data.get("endTime", "23:59"), time(23, 59))
            is_open = start <= now_t <= end
            open_any = open_any or is_open
            print(
                f"    {nid:<6} {start.strftime('%H:%M')}-{end.strftime('%H:%M')}  "
                f"{'OPEN' if is_open else 'closed'}"
            )
        if not open_any:
            blockers.append(
                "Every time window is closed right now, so no leg can fire until one "
                "opens."
            )

    print()
    if blockers:
        print(f"{len(blockers)} reason(s) orders are not being placed:\n")
        for i, blocker in enumerate(blockers, 1):
            print(f"  {i}. {blocker}\n")
    else:
        print(
            "No blocking condition found. The workflow is active, in a window, and\n"
            "pointed at the live broker - so the strategy's own entry conditions are\n"
            "simply not true yet. Open the latest execution to see which one is false."
        )
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: uv run python scripts/flow_diagnose.py <workflow_id>")
        return 2
    return diagnose(int(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
