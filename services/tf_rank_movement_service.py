"""TF Boost rank-movement engine — Phase 1B of the Intraday Boost plan.

Turns a symbol's current-day rank timeline (the [minute_of_day, rank] pairs the
snapshot recorder already stores) into current-day movement state: where it is,
where it came from, and how fast. This is the authoritative interpretation the
plan wants to live in the backend rather than inside one React component.

Two layers, deliberately split like services/risk/:

- `compute_rank_state` / `compute_rank_states` are PURE. Given the observations
  they return a RankState; no DB, no clock, no network. That is what makes them
  trivially testable and identical for every consumer.
- `rank_movement_service` is the thin I/O wrapper: it pulls the day's timeline
  from the isolated DuckDB and calls the pure core.

Reconstructable from the current-day snapshots alone (plan §38), so a backend
restart recovers the day's movement without any extra persistence.

Rank convention throughout: a LOWER rank number is better (#1 is strongest).
`rank_delta = previous_rank - current_rank`, so positive means improved. Only
the fields the plan's Phase 1B calls for are computed here; Top-N, sustained
position and event classification are later phases (1C-1E).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from database.tf_boost_db import get_boost_rank_timeline
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RankState:
    """Current-day movement state for one symbol, derived from its observations.

    Fields that need at least two observations to mean anything (previous_rank,
    rank_delta, the velocities, acceleration) are None until then: the first
    observation is a baseline, not a movement event (plan §40), and the engine
    never fabricates a value it did not observe (plan §41)."""

    symbol: str
    observations: int
    current_rank: int
    previous_rank: int | None
    first_seen_rank: int
    best_rank: int
    worst_rank: int

    first_seen_min: int
    last_seen_min: int
    previous_seen_min: int | None

    rank_delta: int | None  # previous_rank - current_rank; + = improved
    rank_change_since_first_seen: int  # first_seen_rank - current_rank
    rank_velocity: float | None  # ranks improved per minute over the last step
    rank_acceleration: float | None  # last step velocity - prior step velocity

    consecutive_improving: int  # trailing steps that improved (rank fell)
    consecutive_deteriorating: int  # trailing steps that worsened (rank rose)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_rank_state(symbol: str, observations: list[list[int]]) -> RankState | None:
    """Pure: fold one symbol's [minute_of_day, rank] pairs into a RankState.

    `observations` must be time-ordered (the DB returns them sorted). Repeated
    or out-of-order minutes are tolerated: a pair whose minute is not strictly
    after the last kept one is skipped, so a duplicate snapshot cannot invent a
    zero-elapsed step (which would divide by zero in the velocity). Returns None
    if there is nothing usable.
    """
    # Keep only strictly-increasing minutes, guarding against dupes/disorder.
    clean: list[tuple[int, int]] = []
    for pair in observations:
        if not pair or len(pair) < 2:
            continue
        m, r = int(pair[0]), int(pair[1])
        if clean and m <= clean[-1][0]:
            continue
        clean.append((m, r))
    if not clean:
        return None

    first_min, first_rank = clean[0]
    last_min, current_rank = clean[-1]
    best_rank = min(r for _, r in clean)
    worst_rank = max(r for _, r in clean)

    previous_rank = previous_min = rank_delta = rank_velocity = rank_acceleration = None
    prev_velocity = None
    consec_improve = consec_deteriorate = 0

    # Walk the steps once, carrying the previous step's velocity so the last
    # step's acceleration is the change in velocity. Each step uses the ACTUAL
    # elapsed minutes, so a gap (missing snapshot) widens the denominator rather
    # than being filled in.
    for (m0, r0), (m1, r1) in zip(clean, clean[1:], strict=False):
        dt = m1 - m0  # > 0 by construction
        velocity = (r0 - r1) / dt
        if prev_velocity is not None:
            rank_acceleration = velocity - prev_velocity
        prev_velocity = velocity

        # Trailing runs of improvement / deterioration, reset on a reversal.
        if r1 < r0:
            consec_improve += 1
            consec_deteriorate = 0
        elif r1 > r0:
            consec_deteriorate += 1
            consec_improve = 0
        else:
            consec_improve = consec_deteriorate = 0

        previous_rank, previous_min = r0, m0
        rank_delta = r0 - r1
        rank_velocity = velocity

    return RankState(
        symbol=symbol,
        observations=len(clean),
        current_rank=current_rank,
        previous_rank=previous_rank,
        first_seen_rank=first_rank,
        best_rank=best_rank,
        worst_rank=worst_rank,
        first_seen_min=first_min,
        last_seen_min=last_min,
        previous_seen_min=previous_min,
        rank_delta=rank_delta,
        rank_change_since_first_seen=first_rank - current_rank,
        rank_velocity=rank_velocity,
        rank_acceleration=rank_acceleration,
        consecutive_improving=consec_improve,
        consecutive_deteriorating=consec_deteriorate,
    )


def compute_rank_states(timeline: dict[str, list[list[int]]]) -> dict[str, RankState]:
    """Pure: {symbol: [[minute, rank], ...]} -> {symbol: RankState}."""
    out: dict[str, RankState] = {}
    for symbol, obs in timeline.items():
        state = compute_rank_state(symbol, obs)
        if state is not None:
            out[symbol] = state
    return out


def rank_movement_service(
    date: str = "",
    list_type: str = "intraday_boost",
) -> dict[str, RankState]:
    """I/O wrapper: reconstruct the day's per-symbol rank states from DuckDB.

    `date` defaults to today (naive IST, matching how the recorder stores
    snapshot_date). Degrades to {} on any read failure, like the query service.
    """
    day = date or datetime.now().strftime("%Y-%m-%d")
    # get_boost_rank_timeline returns {symbol: {day: [[min, rank], ...]}}.
    per_symbol_days = get_boost_rank_timeline(day, day, list_type)
    timeline = {sym: days.get(day, []) for sym, days in per_symbol_days.items()}
    return compute_rank_states(timeline)


def _demo() -> None:
    """Self-check on the plan's canonical sequences (§75, §89). Run directly."""
    # §27 rapid climb 62 -> 1 over 09:15..09:29 (2-min grid).
    climb = [[555, 62], [557, 58], [559, 45], [561, 40], [563, 20], [565, 8], [567, 3], [569, 1]]
    s = compute_rank_state("PATANJALI", climb)
    assert s.current_rank == 1 and s.first_seen_rank == 62 and s.best_rank == 1
    assert s.previous_rank == 3 and s.rank_delta == 2  # 3 -> 1
    assert s.rank_change_since_first_seen == 61
    assert s.rank_velocity == 1.0  # (3-1)/2 min
    assert s.consecutive_improving == 7 and s.consecutive_deteriorating == 0

    # §19 velocity depends on elapsed time: 62 -> 20 in 4 min vs 30 min.
    fast = compute_rank_state("A", [[0, 62], [4, 20]])
    slow = compute_rank_state("B", [[0, 62], [30, 20]])
    assert fast.rank_velocity == 42 / 4 and slow.rank_velocity == 42 / 30
    assert fast.rank_velocity > slow.rank_velocity

    # §20 acceleration: improvement itself increasing (62->55->47->30->18, 2-min steps).
    acc = compute_rank_state("C", [[0, 62], [2, 55], [4, 47], [6, 30], [8, 18]])
    # last step velocity (30->18)/2=6, prior (47->30)/2=8.5 -> accel = 6-8.5 = -2.5?
    # ranks: deltas 7,8,17,12 over 2 min each -> vels 3.5,4,8.5,6. accel last = 6-8.5.
    assert acc.rank_acceleration == 6.0 - 8.5

    # §40 baseline: a single observation is not a movement event.
    base = compute_rank_state("NEW", [[100, 15]])
    assert base.previous_rank is None and base.rank_delta is None
    assert base.rank_velocity is None and base.rank_acceleration is None
    assert base.first_seen_rank == 15 and base.current_rank == 15

    # §29 false/unstable jump 62->20->48->17->55: net movement, not a clean climb.
    unstable = compute_rank_state("D", [[0, 62], [2, 20], [4, 48], [6, 17], [8, 55]])
    assert unstable.consecutive_improving == 0  # last step 17->55 deteriorated
    assert unstable.consecutive_deteriorating == 1
    assert unstable.best_rank == 17 and unstable.worst_rank == 62

    # §41 missing snapshots: 09:15,09:17,09:23,09:25 - velocity uses real elapsed time.
    gap = compute_rank_state("E", [[555, 60], [557, 50], [563, 40], [565, 30]])
    assert gap.rank_velocity == (40 - 30) / 2  # last step 09:23->09:25
    assert gap.observations == 4

    # Duplicate/disordered minutes are dropped, never a divide-by-zero.
    dup = compute_rank_state("F", [[0, 10], [0, 9], [2, 8], [1, 99]])
    assert dup.observations == 2 and dup.current_rank == 8

    print("tf_rank_movement _demo: all assertions passed")


if __name__ == "__main__":
    _demo()
