"""Compare the badge's rating gate across every captured day.

    uv run python scripts/tf_boost_gate_compare.py 2026-09-17 2026-09-18

The open question from 18-Sep-2026: the gate asks whether a symbol has climbed
ten places SINCE FIRST SEEN, which hides a stock that sank and then recovered.
ADANIGREEN fell to rank 73, climbed 55 places back to 18 on a +4.6% move, and
badged 85 minutes after its run began because the gate was still comparing with
its first-seen 30.

Measuring from the trough catches it and costs accuracy: on 17-Sep it took paid
from 37% to 28%. The middle ground -- rate from the trough, keep force from
first seen -- was mildly better on both days and is the candidate.

Two days cannot settle it. Run this over a week, split rising days from falling
ones, and only move the gate if the candidate wins on both.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.tf_boost_db import (  # noqa: E402
    get_boost_change_timeline,
    get_boost_rank_timeline_fine,
)
from services.tf_rank_movement_service import (  # noqa: E402
    RUN_LEADER_RANK,
    RUN_MIN_CLIMB,
    RUN_MIN_OBS,
    compute_rank_state,
    compute_run,
)


def evaluate(D, gate):
    ch = get_boost_change_timeline(D)
    rk = get_boost_rank_timeline_fine(D)
    out = []
    for s in ch:
        cps = ch[s][D]
        rps = rk.get(s, {}).get(D, [])
        if len(cps) < RUN_MIN_OBS + 2 or not rps:
            continue
        for i in range(RUN_MIN_OBS, len(cps)):
            upto = cps[i][0]
            run = compute_run(cps[: i + 1])
            if not run or not run.is_clean or run.direction is None:
                continue
            st = compute_rank_state(s, [p for p in rps if p[0] <= upto])
            if not st or not gate(st):
                continue
            after = [v for m, v in cps if m >= upto]
            entry = after[0]
            up = run.direction == "up"
            right = wrong = None
            for v in after:
                move = (v - entry) if up else (entry - v)
                if right is None and move >= 0.5:
                    right = True
                if wrong is None and move <= -0.5:
                    wrong = True
                if right or wrong:
                    break
            paid = any(((v - entry) if up else (entry - v)) >= 1.0 for v in after)
            out.append((s, upto, bool(right) and not wrong, paid, run.direction))
            break
    return out


GATES = {
    # The candidate from 18-Sep-2026: rate the symbol on how far it has climbed
    # from its OWN trough, while keeping force measured from first seen. Catches a
    # stock that sank and recovered -- ADANIGREEN, rank 73 back to 18 on a +4.6%
    # move -- which the first-seen gate cannot see.
    "CANDIDATE trough rated (>=20), force from first seen": lambda st: (
        (st.current_rank <= RUN_LEADER_RANK or (st.worst_rank - st.current_rank) >= 20)
        and st.rank_change_since_first_seen >= 0
    ),
    "current: rated+force from first seen": lambda st: (
        (
            st.current_rank <= RUN_LEADER_RANK
            or (st.first_seen_rank - st.current_rank) >= RUN_MIN_CLIMB
        )
        and st.rank_change_since_first_seen >= 0
    ),
    "from the trough: rated+force from worst": lambda st: (
        (st.current_rank <= RUN_LEADER_RANK or (st.worst_rank - st.current_rank) >= RUN_MIN_CLIMB)
        and st.current_rank <= st.worst_rank
    ),
    "trough rated, no force gate": lambda st: (
        st.current_rank <= RUN_LEADER_RANK or (st.worst_rank - st.current_rank) >= RUN_MIN_CLIMB
    ),
}
days = sys.argv[1:] or ["2026-09-17", "2026-09-18"]
for D in days:
    print(f"\n{D}")
    print(f"{'gate':<40}{'badges':>8}{'dir right':>11}{'paid':>10}")
    for label, g in GATES.items():
        b = evaluate(D, g)
        r = sum(1 for x in b if x[2])
        p = sum(1 for x in b if x[3])
        print(
            f"{label:<40}{len(b):>8}{r:>6} ({r / max(1, len(b)) * 100:>3.0f}%){p:>5} ({p / max(1, len(b)) * 100:>3.0f}%)"
        )
