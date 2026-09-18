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
from zoneinfo import ZoneInfo

from database.tf_boost_db import (
    get_boost_change_timeline,
    get_boost_rank_timeline_fine,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# The recorder stamps rows in IST (services/tf_boost_snapshot_service), so the
# "today" this engine reads must be IST too -- not the host's local date, which
# is the same thing only by luck of where the server happens to run.
IST = ZoneInfo("Asia/Kolkata")


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
    clean = _clean_observations(observations)
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


# Top-N zones the engine tracks, best (smallest) first. Centralized here rather
# than hardcoded per call site (plan §21/§86); Top-30 can be added if a consumer
# ever needs it, but nothing does today.
TOP_N_THRESHOLDS: tuple[int, ...] = (5, 10, 20)


@dataclass
class TopNZone:
    """A symbol's current-day standing in one Top-N zone (rank <= threshold).

    Times are minutes-of-day. `continuous_min` is the span of the open stretch
    since the last entry (0 when outside); `cumulative_min` sums every stretch
    spent inside today. Durations are measured between observed minutes, so a
    gap in the snapshots widens them honestly rather than being invented."""

    threshold: int
    inside: bool
    entered_min: int | None
    entries: int
    continuous_min: int
    cumulative_min: int
    last_event: str | None
    last_event_min: int | None


@dataclass
class TopNTransition:
    """A single threshold crossing. kind is ENTRY (first time in the zone today),
    RE_ENTRY (a later entry after having left it, plan §25), or EXIT."""

    minute: int
    threshold: int
    kind: str  # 'ENTRY' | 'RE_ENTRY' | 'EXIT'


def _clean_observations(observations, cast=int):
    """Strictly-increasing [minute, value] pairs; shared by the movement, Top-N
    and directional-run passes so they all see the same de-duplicated series.

    The minute is a FLOAT because the recorder samples twice a minute -- 604.5
    is 10:04:30 -- so a badge can reach the screen inside 40 seconds. Rounding
    it to a whole minute made the second sample of each minute collide with the
    first and be dropped, which would have thrown half the record away while
    looking like it worked.

    `cast` is what the second element is: a rank is an int, a change_pct is a
    float and must stay one -- truncating it turned every move into a whole
    number of percent and every give-back into 0 or 1.
    """
    clean: list[tuple[float, float]] = []
    for pair in observations:
        if not pair or len(pair) < 2:
            continue
        m, r = float(pair[0]), cast(pair[1])
        if clean and m <= clean[-1][0]:
            continue
        clean.append((m, r))
    return clean


def compute_topn(
    symbol: str,
    observations: list[list[int]],
    thresholds: tuple[int, ...] = TOP_N_THRESHOLDS,
) -> tuple[dict[int, TopNZone], list[TopNTransition]]:
    """Pure: fold a symbol's timeline into per-zone standing plus the ordered
    list of its threshold crossings.

    A crossing fires only on the boundary (outside->inside or inside->outside),
    so a symbol that sits inside Top-10 for an hour produces one ENTRY, not
    thirty (plan §22). A symbol that simply stops appearing in the list is left
    inside with its last-known standing rather than being forced to EXIT (plan
    §42) -- an absent snapshot is not a rank.
    """
    clean = _clean_observations(observations)
    zones: dict[int, TopNZone] = {}
    transitions: list[TopNTransition] = []

    for n in thresholds:
        inside = False
        entered_min: int | None = None
        last_inside_min: int | None = None
        entries = 0
        cumulative = 0
        last_event: str | None = None
        last_event_min: int | None = None

        for m, r in clean:
            now_inside = r <= n
            if now_inside and not inside:
                entries += 1
                entered_min = m
                last_inside_min = m
                kind = "ENTRY" if entries == 1 else "RE_ENTRY"
                transitions.append(TopNTransition(m, n, kind))
                last_event = f"TOP{n}_{kind}"
                last_event_min = m
            elif now_inside and inside:
                last_inside_min = m
            elif (not now_inside) and inside:
                # First observation back outside: close the stretch at the last
                # minute the symbol was actually seen inside, not this one.
                if entered_min is not None and last_inside_min is not None:
                    cumulative += last_inside_min - entered_min
                transitions.append(TopNTransition(m, n, "EXIT"))
                last_event = f"TOP{n}_EXIT"
                last_event_min = m
                entered_min = None
            inside = now_inside

        continuous = 0
        if inside and entered_min is not None and last_inside_min is not None:
            continuous = last_inside_min - entered_min
            cumulative += continuous

        zones[n] = TopNZone(
            threshold=n,
            inside=inside,
            entered_min=entered_min,
            entries=entries,
            continuous_min=continuous,
            cumulative_min=cumulative,
            last_event=last_event,
            last_event_min=last_event_min,
        )

    return zones, transitions


# --- Phase 1D: sustained position / rank-zone -------------------------------
# A rolling window over the most recent observations, so an established strong
# zone (e.g. 6-9) is told apart from a one-off spike (9, 2, 17). Constants are
# deliberately plain defaults, not tuned (plan §78) -- refine from live data.
SUSTAINED_WINDOW = 6  # most-recent observations considered
SUSTAINED_MIN_OBS = 3  # need at least this many before calling anything sustained
STABLE_ZONE_MAX_SPREAD = 5  # worst-minus-best within the window to count as a zone


@dataclass
class SustainedState:
    """Rolling-window view of how settled a symbol's rank is right now."""

    window: int  # observations actually in the window
    zone_low: int  # best (smallest) rank in the window
    zone_high: int  # worst (largest) rank in the window
    zone_spread: int  # zone_high - zone_low
    zone_median: float
    is_stable_zone: bool  # enough observations, tight enough spread
    sustained_top5: bool
    sustained_top10: bool
    sustained_top20: bool


def _median(values: list[int]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2


def compute_sustained(
    symbol: str,
    observations: list[list[int]],
    window: int = SUSTAINED_WINDOW,
    max_spread: int = STABLE_ZONE_MAX_SPREAD,
    thresholds: tuple[int, ...] = TOP_N_THRESHOLDS,
) -> SustainedState | None:
    """Pure: fold the last `window` observations into a stability view.

    `is_stable_zone` needs both enough evidence (>= SUSTAINED_MIN_OBS) and a
    tight spread, so a chop like 9, 2, 17 (spread 15) is never called a zone
    (plan §24). `sustained_topN` means every observation in the window sat
    inside Top-N -- an established position, not one tick that touched it."""
    clean = _clean_observations(observations)
    if not clean:
        return None
    win = [r for _, r in clean[-window:]]
    low, high = min(win), max(win)
    spread = high - low
    # Sustained means SETTLED, not merely "every recent tick happened to be
    # inside": a symbol still climbing 8 -> 3 -> 1 sits inside Top-10 the whole
    # way but is not established there. So the flags require the same tight
    # spread that defines a stable zone (plan §23/§24).
    stable = len(win) >= SUSTAINED_MIN_OBS and spread <= max_spread
    return SustainedState(
        window=len(win),
        zone_low=low,
        zone_high=high,
        zone_spread=spread,
        zone_median=_median(win),
        is_stable_zone=stable,
        sustained_top5=stable and high <= thresholds[0],
        sustained_top10=stable and high <= thresholds[1],
        sustained_top20=stable and high <= thresholds[2],
    )


# --- Phase 2: directional run (price) ---------------------------------------
# What a trader means by "it is going one way and not giving it back". The
# candles said this plainly on 17-Sep-2026: the day's best names had barely more
# green 5-minute bars than red (SBILIFE 57%, HDFCLIFE 52%, ALKEM 48%) and half
# of every bar was wick, so a run of green candles is not the signal. What
# separated them was the deepest pullback from the running extreme -- under 1%
# for every winner against a 3-4% move, and 3.07% for HYUNDAI, which went
# nowhere. So a run is measured as move against give-back, not as a streak.
#
# Untuned starting points (plan §78): review them against a live session before
# trusting the thresholds, and expect the numbers, not the flag, to do the work.
RUN_MIN_OBS = 10  # observations before the shape means anything
# Points of change_pct between the turn and now. Lowered from 1.0 to 0.6 on the
# evidence of 17-Sep-2026, where the higher floor was hiding clean movers rather
# than filtering noise. Replaying the day and acting on the badge:
#
#   floor   flags   went on to pay   rate   median flag time
#    1.00      61              14     23%              10:13
#    0.60      73              19     26%              10:04
#    0.50      75              21     28%              09:53
#
# More signals, earlier, and the hit rate does not fall -- which is the failure
# a looser filter normally shows. 0.6 is the conservative end of the 0.4-0.6
# band the day supports; below 0.5 nothing further is gained. DRREDDY climbed
# 59->20 giving back 0.21 points and was blocked by the old floor for half an
# hour; SBILIFE was blocked at 10:15 with an efficiency of 5.1.
#
# This is one day, and one day cannot settle a threshold. Review it against the
# week's recorded data before trusting it.
RUN_MIN_MOVE_PCT = 0.6
RUN_MIN_EFFICIENCY = 3.0  # move divided by give-back
RUN_ADVERSE_FLOOR = 0.15  # a move that never pulled back still divides by this
# A clean run only counts as an event for a symbol the list already rates: a
# leader, or one that has climbed its way up today.
RUN_LEADER_RANK = 20
RUN_MIN_CLIMB = 10
# Down runs are off, and this is a measured decision rather than a preference.
# The old rule suppressed them as a side effect of getting the rank logic
# backwards, which flattered it: replaying 17-Sep-2026, the badge that followed
# a down run was right 4 times in 13 once the logic was corrected, and 2 in 5
# before that. Their options were worse still -- 1 of 4 profitable, median -19%
# against +102% and +92% for the two best up runs. Up runs only scores 59% on
# direction and 44% on reaching +1%, matching the old rule's numbers without
# borrowing its mistake.
#
# On at Aakash's request, 18-Sep-2026, and he was right to ask. The numbers
# above come from 17-Sep-2026, which was a strongly rising day: 64 of the list
# up against 15 down. Shorts failing on a day like that says almost nothing
# about the signal, and the market does not only rise -- some days the decline
# IS the move worth taking. Judging down runs on a single up-day was the error,
# not showing them.
#
# The week's study records each day's breadth for exactly this reason, so an
# aggregate can separate a rising day from a falling one instead of averaging
# the two into nonsense.
RUN_ALLOW_DOWN = True
# The first prints of the day are not prices anyone traded. Measured on
# 17-Sep-2026: the 09:15 and 09:16 snapshots carry the same pre-open figure and
# the 09:16->09:17 correction has a median of 1.38 points and a worst of 8.93 --
# PATANJALI read +7.43% and was -0.86% a minute later. Anchoring a run there
# invented a 10-point "fall" in a stock that closed down 2.84%. Everything
# before this minute is dropped from the run entirely; by 09:20 the median
# minute-to-minute move is 0.11 points, which is a market, not an artefact.
RUN_SETTLE_MIN = 9 * 60 + 20


@dataclass
class RunState:
    """How one-directional the current move is, and how much it gave back."""

    observations: int
    direction: str | None  # 'up' | 'down' | None when it has not moved at all
    move_pct: float  # change_pct now minus change_pct at the turn
    adverse_pct: float  # deepest pullback since the turn, in points
    efficiency: float  # abs(move) / max(adverse, RUN_ADVERSE_FLOOR)
    from_min: int  # minute-of-day the run started
    run_minutes: int  # how long it has been running
    is_clean: bool  # moved enough, and kept most of it


def compute_run(
    changes: list[list[float]],
    min_obs: int = RUN_MIN_OBS,
    min_move: float = RUN_MIN_MOVE_PCT,
    min_efficiency: float = RUN_MIN_EFFICIENCY,
    settle_min: int = RUN_SETTLE_MIN,
) -> RunState | None:
    """Pure: fold [[minute, change_pct], ...] into the shape of the current move.

    The run is anchored where the current direction began -- the day's low for an
    up move, its high for a down one -- not at the first observation. Measuring
    from the open charges a stock for a shakeout it has long since left behind:
    SBILIFE on 17-Sep-2026 opened +2.79%, fell to +1.08% by 10:21 and then rose
    all day to +4.25%. From the open that reads as a 2.29-point give-back and no
    run at all; from the 09:56 turn it is a 3.75-point move that gave back 0.65,
    which is what the trader watching it saw.

    Direction is whichever end of the day is further from here, so a stock that
    turned down in the afternoon reports the decline it is in now.
    """
    clean = [p for p in _clean_observations(changes, cast=float) if p[0] >= settle_min]
    if len(clean) < min_obs:
        return None
    values = [v for _, v in clean]
    now = values[-1]
    low_i, high_i = values.index(min(values)), values.index(max(values))
    up_move, down_move = now - values[low_i], now - values[high_i]

    if up_move == 0 and down_move == 0:
        direction, anchor, move = None, len(values) - 1, 0.0
    elif abs(up_move) >= abs(down_move):
        direction, anchor, move = "up", low_i, up_move
    else:
        direction, anchor, move = "down", high_i, down_move

    adverse = 0.0
    if direction is not None:
        extreme = values[anchor]
        for value in values[anchor:]:
            extreme = max(extreme, value) if direction == "up" else min(extreme, value)
            give_back = (extreme - value) if direction == "up" else (value - extreme)
            adverse = max(adverse, give_back)

    efficiency = abs(move) / max(adverse, RUN_ADVERSE_FLOOR)
    return RunState(
        observations=len(clean),
        direction=direction,
        move_pct=round(move, 2),
        adverse_pct=round(adverse, 2),
        efficiency=round(efficiency, 2),
        from_min=clean[anchor][0],
        run_minutes=clean[-1][0] - clean[anchor][0],
        is_clean=(direction is not None and abs(move) >= min_move and efficiency >= min_efficiency),
    )


# --- Phase 1E: event classification -----------------------------------------
# One salient label per symbol for the current step, chosen by priority (plan
# §59/§60). Jump thresholds act on a single step's rank_delta; fast-climb on the
# step's velocity. Not tuned -- plain starting points (plan §78).
RANK_JUMP_LARGE = 15
RANK_JUMP_EXTREME = 30
FAST_CLIMB_MIN_VELOCITY = 5.0

# Higher wins when several apply. Exit/drop rank below climbs so a symbol that
# entered Top-5 on a fast move reads as the entry, not the drop it also had.
_EVENT_PRIORITY: dict[str, int] = {
    # A symbol not on the current list has no current event -- see ABSENT below.
    "EXTREME_JUMP": 100,
    # A clean directional run outranks a fast climb: it is the state a trader is
    # actually looking for, and it has held all day rather than for one step.
    "CLEAN_RUN_UP": 85,
    "CLEAN_RUN_DOWN": 84,
    "LARGE_JUMP": 90,
    "FAST_CLIMB": 80,
    "TOP5_ENTRY": 75,
    "TOP5_RE_ENTRY": 74,
    "TOP10_ENTRY": 70,
    "TOP10_RE_ENTRY": 69,
    "TOP20_ENTRY": 60,
    "TOP20_RE_ENTRY": 59,
    "SUSTAINED_TOP5": 55,
    "SUSTAINED_TOP10": 50,
    "SUSTAINED_TOP20": 45,
    "CLIMBING": 30,
    "FAST_DROP": 25,
    "TOP5_EXIT": 22,
    "TOP10_EXIT": 21,
    "TOP20_EXIT": 20,
    "FALLING": 15,
    "NEW": 10,
    "NORMAL": 0,
    # Not on the latest snapshot: its standing is last-known, not current
    # (plan §42). Kept at the bottom so no consumer alerts on it.
    "ABSENT": 0,
}

# A symbol is "present" if it appears in the latest snapshot, allowing for one
# missed write. Beyond that its event is history, not news: on 17-Sep-2026 every
# symbol the engine reported at alert strength had last been seen at 09:17, six
# hours earlier, because an event stays frozen at the symbol's last observation.
PRESENCE_TOLERANCE_MIN = 2


def classify_event(
    state: RankState,
    zones: dict[int, TopNZone],
    transitions: list[TopNTransition],
    sustained: SustainedState | None,
    run: RunState | None = None,
) -> tuple[str, int]:
    """Pure: pick the single most salient event for the symbol's latest step.

    Only transitions that happened on the latest observed minute count as the
    current event, so a Top-10 entry ten minutes ago does not keep re-firing
    (plan §22/§58); its lasting form is SUSTAINED_TOP10 via the window.

    A crossing recorded on the symbol's FIRST observation is not one: we never
    saw it outside the zone, so being there is where it started, not something
    it just did (plan §40). Without this the 09:15 snapshot classifies the whole
    opening list as Top-5/10/20 entries -- the entire top 20 would alert in the
    first minute of every session, and none of it would be movement."""
    candidates: list[str] = []

    for t in transitions:
        if t.minute == state.last_seen_min and t.minute != state.first_seen_min:
            candidates.append(f"TOP{t.threshold}_{t.kind}")

    d = state.rank_delta
    if d is not None:
        if d >= RANK_JUMP_EXTREME:
            candidates.append("EXTREME_JUMP")
        elif d >= RANK_JUMP_LARGE:
            candidates.append("LARGE_JUMP")
        if d <= -RANK_JUMP_LARGE:
            candidates.append("FAST_DROP")
        elif d > 0:
            candidates.append("CLIMBING")
        elif d < 0:
            candidates.append("FALLING")

    if state.rank_velocity is not None and state.rank_velocity >= FAST_CLIMB_MIN_VELOCITY:
        candidates.append("FAST_CLIMB")

    if sustained is not None:
        if sustained.sustained_top5:
            candidates.append("SUSTAINED_TOP5")
        elif sustained.sustained_top10:
            candidates.append("SUSTAINED_TOP10")
        elif sustained.sustained_top20:
            candidates.append("SUSTAINED_TOP20")

    # A clean run is only news for a symbol the list already rates -- a leader,
    # or one that climbed here today. Otherwise a quiet stock drifting one way
    # at rank 90 would outrank everything actually happening.
    if run is not None and run.is_clean and run.direction is not None:
        rated = (
            state.current_rank <= RUN_LEADER_RANK
            or (state.first_seen_rank - state.current_rank) >= RUN_MIN_CLIMB
        )
        # The price direction must agree with what the ranked list is saying.
        # MFSL on 17-Sep-2026 had eleven minutes of data, five of them a
        # pullback from +1.70% to +0.89%, and was called a clean DOWN run while
        # sitting sixth on a strength list and up on the day. It then rose 4%,
        # so the put that badge pointed at lost 66% while the call made 135%.
        # Across the day's badges, requiring agreement lifted direction accuracy
        # from 49% to 58% and the share reaching +1% from 34% to 44%, on 59
        # badges rather than 73.
        # A rank that is holding or climbing means the move has FORCE. It does
        # not mean the move is upward, which is what an earlier version of this
        # assumed -- and Aakash caught it on DIXON, 18-Sep-2026:
        #
        #   10:24  rank 27  -0.84%      10:27  rank 16  -1.22%
        #   10:28  rank  8  -1.55%      score rising 1.1 -> 1.7 as it fell
        #
        # The list ranks by momentum score, so a stock falling hard CLIMBS it.
        # Measured across that morning: rank improved in 69% of falling stocks
        # against 22% of rising ones. Requiring a down run's rank to deteriorate
        # therefore rejected the real decliners -- DIXON 27->9, MARUTI 66->13,
        # SUNPHARMA 43->12 -- and kept only the ones losing force.
        #
        # So force is read the same way in both directions, and the direction
        # itself comes from price alone.
        has_force = state.rank_change_since_first_seen >= 0
        if rated and has_force and (run.direction == "up" or RUN_ALLOW_DOWN):
            candidates.append("CLEAN_RUN_UP" if run.direction == "up" else "CLEAN_RUN_DOWN")

    if state.observations == 1:
        candidates.append("NEW")
    if not candidates:
        candidates.append("NORMAL")

    event = max(candidates, key=lambda e: _EVENT_PRIORITY.get(e, 0))
    return event, _EVENT_PRIORITY.get(event, 0)


def compute_symbol_movement(
    symbol: str,
    observations: list[list[int]],
    latest_minute: int | None = None,
    changes: list[list[float]] | None = None,
) -> dict | None:
    """Pure: the full current-day picture for one symbol as a flat dict — the
    RankUIModel the API and frontend consume (plan §49/§92). None if unusable.

    `latest_minute` is the most recent minute ANY symbol was snapshotted for
    this list today. Pass it and a symbol missing from that snapshot is reported
    as `present=False` with the event ABSENT: its rank, trajectory and Top-N
    standing stay available as last-known (plan §42), but it no longer claims a
    current event, so nothing badges or alerts on a move that stopped hours ago.
    Omit it and every symbol is treated as present, which is only right for a
    single-symbol call in a test."""
    state = compute_rank_state(symbol, observations)
    if state is None:
        return None
    zones, transitions = compute_topn(symbol, observations)
    sustained = compute_sustained(symbol, observations)
    run = compute_run(changes) if changes else None
    event, priority = classify_event(state, zones, transitions, sustained, run)
    stale_by = 0 if latest_minute is None else max(0, latest_minute - state.last_seen_min)
    present = stale_by <= PRESENCE_TOLERANCE_MIN
    if not present:
        event, priority = "ABSENT", _EVENT_PRIORITY["ABSENT"]
    out = state.to_dict()
    out.update(
        {
            "top5": zones[5].inside,
            "top10": zones[10].inside,
            "top20": zones[20].inside,
            "top5_entries": zones[5].entries,
            "top10_entries": zones[10].entries,
            "top20_entries": zones[20].entries,
            "sustained_top5": bool(sustained and sustained.sustained_top5),
            "sustained_top10": bool(sustained and sustained.sustained_top10),
            "sustained_top20": bool(sustained and sustained.sustained_top20),
            "zone_low": sustained.zone_low if sustained else None,
            "zone_high": sustained.zone_high if sustained else None,
            "zone_median": sustained.zone_median if sustained else None,
            "is_stable_zone": bool(sustained and sustained.is_stable_zone),
            "event": event,
            "event_priority": priority,
            "present": present,
            "minutes_since_last_seen": stale_by,
            # Phase 2 directional run -- None throughout when the day has no
            # price rows yet, so an older consumer simply shows nothing.
            "run_direction": run.direction if run else None,
            "run_move_pct": run.move_pct if run else None,
            "run_adverse_pct": run.adverse_pct if run else None,
            "run_efficiency": run.efficiency if run else None,
            "run_minutes": run.run_minutes if run else None,
            "run_from_min": run.from_min if run else None,
            "run_clean": bool(run and run.is_clean),
            # The stock's actual move against yesterday's close. Carried beside
            # the run so the two can never be confused: a run of 10 points from
            # a high is not a 10% fall.
            "day_change_pct": (
                round(float(changes[-1][1]), 2) if changes and len(changes[-1]) > 1 else None
            ),
        }
    )
    return out


def compute_rank_states(timeline: dict[str, list[list[int]]]) -> dict[str, RankState]:
    """Pure: {symbol: [[minute, rank], ...]} -> {symbol: RankState}."""
    out: dict[str, RankState] = {}
    for symbol, obs in timeline.items():
        state = compute_rank_state(symbol, obs)
        if state is not None:
            out[symbol] = state
    return out


def movement_snapshot(date: str = "", list_type: str = "intraday_boost") -> list[dict]:
    """I/O: the day's full per-symbol movement, newest rank first, for the API.

    Reconstructed from the isolated DuckDB; degrades to [] on any read failure,
    like the other query services here."""
    day = date or datetime.now(IST).strftime("%Y-%m-%d")
    # The fine timeline: the recorder samples twice a minute and the engine
    # must see both, or half of every move is invisible to it.
    per_symbol_days = get_boost_rank_timeline_fine(day, day, list_type)
    # The latest minute anyone was recorded at is what "now" means for this
    # list, so it survives a closed market and a replay of an older date alike.
    latest_minute = max(
        (obs[-1][0] for days in per_symbol_days.values() for obs in [days.get(day, [])] if obs),
        default=None,
    )
    per_symbol_changes = get_boost_change_timeline(day, day, list_type)
    rows: list[dict] = []
    for sym, days in per_symbol_days.items():
        row = compute_symbol_movement(
            sym,
            days.get(day, []),
            latest_minute,
            per_symbol_changes.get(sym, {}).get(day, []),
        )
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r["current_rank"])
    return rows


def rank_movement_service(
    date: str = "",
    list_type: str = "intraday_boost",
) -> dict[str, RankState]:
    """I/O wrapper: reconstruct the day's per-symbol rank states from DuckDB.

    `date` defaults to today (naive IST, matching how the recorder stores
    snapshot_date). Degrades to {} on any read failure, like the query service.
    """
    day = date or datetime.now(IST).strftime("%Y-%m-%d")
    # get_boost_rank_timeline returns {symbol: {day: [[min, rank], ...]}}.
    # The fine timeline: the recorder samples twice a minute and the engine
    # must see both, or half of every move is invisible to it.
    per_symbol_days = get_boost_rank_timeline_fine(day, day, list_type)
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

    # §22/§27 Top-N: the 62->1 climb crosses Top-20, Top-10, Top-5 once each.
    zones, trans = compute_topn("PATANJALI", climb)
    assert zones[20].inside and zones[10].inside and zones[5].inside
    assert zones[10].entries == 1 and zones[10].last_event == "TOP10_ENTRY"
    kinds = [(t.threshold, t.kind) for t in trans]
    assert kinds == [(5, "ENTRY"), (10, "ENTRY"), (20, "ENTRY")] or set(kinds) == {
        (20, "ENTRY"),
        (10, "ENTRY"),
        (5, "ENTRY"),
    }

    # §22 no repeat: sitting inside Top-10 for many ticks is one ENTRY, not many.
    inside_long = compute_topn("H", [[0, 8], [2, 7], [4, 9], [6, 6], [8, 8]])
    assert inside_long[0][10].entries == 1
    assert inside_long[0][10].continuous_min == 8  # entered at 0, last inside at 8
    assert len([t for t in inside_long[1] if t.threshold == 10]) == 1

    # §25 re-entry: 8 (in) -> 12,15 (out) -> 9 (in) is ENTRY then EXIT then RE_ENTRY.
    reentry = compute_topn("K", [[0, 8], [2, 12], [4, 15], [6, 9]])
    z10, t10 = reentry[0][10], [t for t in reentry[1] if t.threshold == 10]
    assert z10.entries == 2 and z10.last_event == "TOP10_RE_ENTRY"
    assert [t.kind for t in t10] == ["ENTRY", "EXIT", "RE_ENTRY"]

    # §42 disappearance: last seen inside Top-10, then no more snapshots -> stays
    # inside on last-known standing, no fabricated EXIT.
    vanish = compute_topn("L", [[0, 20], [2, 8]])
    assert vanish[0][10].inside is True
    assert not any(t.kind == "EXIT" for t in vanish[1])

    # §24 sustained zone 6-9 is stable; chop 9,2,17 is not.
    zone = compute_sustained("Z", [[0, 9], [2, 8], [4, 9], [6, 7], [8, 8], [10, 6]])
    assert zone.is_stable_zone and zone.zone_low == 6 and zone.zone_high == 9
    assert zone.zone_spread == 3 and zone.sustained_top10 and not zone.sustained_top5
    chop = compute_sustained("Y", [[0, 9], [2, 2], [4, 17]])
    assert not chop.is_stable_zone  # spread 15

    # §58 an entry only fires on the step it happens: the full 62->1 climb's
    # latest step is 3->1 (a climb), not the earlier Top-5 entry at 8->3.
    ev = compute_symbol_movement("P", climb)
    assert ev["event"] == "CLIMBING" and ev["top5"] is True and ev["current_rank"] == 1

    # §60 event priority: when the latest step IS the Top-5 entry, it wins the climb.
    entry = compute_symbol_movement("Q", [[0, 20], [2, 8], [4, 3]])
    assert entry["event"] == "TOP5_ENTRY" and entry["top5"] is True

    # A single-step 62 -> 20 is a 42-rank delta: extreme jump outranks all else.
    jump = compute_symbol_movement("J", [[0, 62], [2, 20]])
    assert jump["event"] == "EXTREME_JUMP" and jump["rank_delta"] == 42
    # A milder 40 -> 22 (delta 18) is a large, not extreme, jump.
    mild = compute_symbol_movement("J2", [[0, 40], [2, 22]])
    assert mild["event"] == "LARGE_JUMP"

    print("tf_rank_movement _demo: all assertions passed")


if __name__ == "__main__":
    _demo()


@dataclass
class RunEpisode:
    """One stretch during which a symbol carried a RUN badge.

    A badge is a live state: it appears when the move becomes clean and goes
    when it stops being. Drawn on a chart, a stretch is what a trader actually
    wants -- when it started, how long it held, and what the price did inside
    it -- which a single current-state row cannot show.
    """

    direction: str
    start_min: float  # when the badge appeared
    end_min: float  # last minute it was still showing
    anchor_min: float  # where the move itself turned, which precedes the badge
    peak_efficiency: float
    move_pct: float
    ongoing: bool


def run_episodes(symbol: str, ranks: list, changes: list) -> list[RunEpisode]:
    """Pure: replay a symbol's day and return every stretch it carried a badge.

    Walks the series once, asking the same question the panel asked at each
    minute, so an episode is exactly what was on screen rather than a
    reconstruction from the final state. That distinction matters: the final
    state cannot tell you a run ended at 11:20 and another began at 13:05.
    """
    episodes: list[RunEpisode] = []
    current: dict | None = None
    for i in range(RUN_MIN_OBS, len(changes)):
        upto = changes[i][0]
        row = compute_symbol_movement(
            symbol, [p for p in ranks if p[0] <= upto], upto, changes[: i + 1]
        )
        badged = bool(row and row["event"].startswith("CLEAN_RUN"))
        if badged:
            direction = row["run_direction"]
            if current and current["direction"] == direction:
                current["end_min"] = upto
                current["peak_efficiency"] = max(
                    current["peak_efficiency"], row["run_efficiency"] or 0
                )
                current["move_pct"] = row["run_move_pct"]
            else:
                if current:
                    episodes.append(RunEpisode(**current, ongoing=False))
                current = {
                    "direction": direction,
                    "start_min": upto,
                    "end_min": upto,
                    "anchor_min": row["run_from_min"] if row["run_from_min"] is not None else upto,
                    "peak_efficiency": row["run_efficiency"] or 0,
                    "move_pct": row["run_move_pct"] or 0,
                }
        elif current:
            episodes.append(RunEpisode(**current, ongoing=False))
            current = None
    if current:
        episodes.append(RunEpisode(**current, ongoing=True))
    return episodes


def run_episodes_for(symbol: str, date: str = "", list_type: str = "intraday_boost") -> list[dict]:
    """I/O: the day's badge stretches for one symbol, as flat dicts."""
    day = date or datetime.now(IST).strftime("%Y-%m-%d")
    ranks = get_boost_rank_timeline_fine(day, day, list_type).get(symbol, {}).get(day, [])
    changes = get_boost_change_timeline(day, day, list_type).get(symbol, {}).get(day, [])
    if not ranks or len(changes) <= RUN_MIN_OBS:
        return []
    return [asdict(e) for e in run_episodes(symbol, ranks, changes)]
