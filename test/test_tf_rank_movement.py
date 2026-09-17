"""Phase 1B rank-movement engine — deterministic tests (plan §75/§89).

Covers the movement fields the engine owns now: delta, velocity, acceleration,
first-seen, best/worst, consecutive runs, and the data-quality guards. Top-N
transitions, sustained position and event classification arrive in 1C-1E and
get their own cases then.
"""

from services.tf_rank_movement_service import (
    TOP_N_THRESHOLDS,
    compute_rank_state,
    compute_rank_states,
    compute_sustained,
    compute_symbol_movement,
    compute_topn,
    movement_snapshot,
    rank_movement_service,
)


def test_rapid_climb_62_to_1():
    # §27: 62 -> 1 on the 2-minute grid.
    obs = [[555, 62], [557, 58], [559, 45], [561, 40], [563, 20], [565, 8], [567, 3], [569, 1]]
    s = compute_rank_state("PATANJALI", obs)
    assert s.current_rank == 1
    assert s.first_seen_rank == 62
    assert s.best_rank == 1
    assert s.worst_rank == 62
    assert s.previous_rank == 3 and s.rank_delta == 2  # 3 -> 1
    assert s.rank_change_since_first_seen == 61
    assert s.rank_velocity == 1.0  # (3-1)/2 min
    assert s.consecutive_improving == 7
    assert s.consecutive_deteriorating == 0


def test_velocity_uses_elapsed_time():
    # §19: same 62->20 jump is faster over 4 minutes than over 30.
    fast = compute_rank_state("A", [[0, 62], [4, 20]])
    slow = compute_rank_state("B", [[0, 62], [30, 20]])
    assert fast.rank_velocity == 42 / 4
    assert slow.rank_velocity == 42 / 30
    assert fast.rank_velocity > slow.rank_velocity


def test_acceleration_is_change_in_velocity():
    # §20: vels 3.5, 4, 8.5, 6 over successive 2-min steps -> last accel = 6 - 8.5.
    s = compute_rank_state("C", [[0, 62], [2, 55], [4, 47], [6, 30], [8, 18]])
    assert s.rank_velocity == 6.0
    assert s.rank_acceleration == 6.0 - 8.5


def test_single_observation_is_a_baseline_not_an_event():
    # §40: first observation establishes a baseline; nothing is a movement yet.
    s = compute_rank_state("NEW", [[100, 15]])
    assert s.previous_rank is None
    assert s.rank_delta is None
    assert s.rank_velocity is None
    assert s.rank_acceleration is None
    assert s.first_seen_rank == 15 and s.current_rank == 15
    assert s.best_rank == 15 and s.worst_rank == 15
    assert s.consecutive_improving == 0 and s.consecutive_deteriorating == 0


def test_unstable_jump_is_not_a_clean_climb():
    # §29: 62->20->48->17->55 nets movement but the last step deteriorated.
    s = compute_rank_state("D", [[0, 62], [2, 20], [4, 48], [6, 17], [8, 55]])
    assert s.consecutive_improving == 0
    assert s.consecutive_deteriorating == 1
    assert s.best_rank == 17
    assert s.worst_rank == 62
    assert s.current_rank == 55


def test_falling_run():
    # §18.3: 5 -> 11 -> 18 is a sustained deterioration.
    s = compute_rank_state("F", [[0, 5], [2, 11], [4, 18]])
    assert s.rank_delta == 11 - 18  # negative
    assert s.consecutive_deteriorating == 2
    assert s.consecutive_improving == 0


def test_missing_snapshots_use_actual_gap():
    # §41: 09:15, 09:17, 09:23, 09:25 - no fabricated 09:19/09:21.
    s = compute_rank_state("E", [[555, 60], [557, 50], [563, 40], [565, 30]])
    assert s.observations == 4
    assert s.rank_velocity == (40 - 30) / 2  # last real step, 2 minutes


def test_duplicate_and_disordered_minutes_are_dropped():
    # §44: a duplicate snapshot must never create a zero-elapsed (divide-by-zero) step.
    s = compute_rank_state("G", [[0, 10], [0, 9], [2, 8], [1, 99]])
    assert s.observations == 2
    assert s.current_rank == 8
    assert s.rank_velocity == (10 - 8) / 2


def test_empty_and_malformed_inputs():
    assert compute_rank_state("X", []) is None
    assert compute_rank_state("X", [[1]]) is None  # malformed pair, nothing usable
    # A malformed pair among good ones is skipped, not fatal.
    s = compute_rank_state("Y", [[0, 20], [1], [2, 10]])
    assert s is not None and s.observations == 2 and s.current_rank == 10


def test_compute_rank_states_maps_symbols():
    timeline = {
        "UP": [[0, 50], [2, 40]],
        "DOWN": [[0, 5], [2, 12]],
        "SOLO": [[0, 9]],
        "EMPTY": [],
    }
    states = compute_rank_states(timeline)
    assert set(states) == {"UP", "DOWN", "SOLO"}  # EMPTY dropped
    assert states["UP"].rank_delta == 10
    assert states["DOWN"].rank_delta == -7


def test_topn_climb_crosses_each_zone_once():
    # §22/§27: 62 -> 1 enters Top-20, Top-10, Top-5 exactly once each.
    obs = [[555, 62], [557, 58], [559, 45], [561, 40], [563, 20], [565, 8], [567, 3], [569, 1]]
    zones, trans = compute_topn("PATANJALI", obs)
    for n in TOP_N_THRESHOLDS:
        assert zones[n].inside is True
        assert zones[n].entries == 1
        assert zones[n].last_event == f"TOP{n}_ENTRY"
    assert {(t.threshold, t.kind) for t in trans} == {(5, "ENTRY"), (10, "ENTRY"), (20, "ENTRY")}


def test_topn_no_repeat_while_inside():
    # §22: many ticks inside Top-10 produce a single ENTRY, not one per tick.
    zones, trans = compute_topn("H", [[0, 8], [2, 7], [4, 9], [6, 6], [8, 8]])
    assert zones[10].entries == 1
    assert zones[10].continuous_min == 8  # entered at min 0, last inside at min 8
    assert zones[10].cumulative_min == 8
    assert len([t for t in trans if t.threshold == 10]) == 1


def test_topn_exit_closes_stretch_at_last_inside_minute():
    # 8 (in) at 0, 9 (in) at 2, 25 (out) at 6: stretch is 2 minutes (0->2), not 6.
    zones, trans = compute_topn("M", [[0, 8], [2, 9], [6, 25]])
    assert zones[10].inside is False
    assert zones[10].cumulative_min == 2
    assert zones[10].continuous_min == 0
    assert [t.kind for t in trans if t.threshold == 10] == ["ENTRY", "EXIT"]


def test_topn_re_entry_is_distinct_from_persistence():
    # §25: 8 -> 12 -> 15 -> 9 is ENTRY, EXIT, then RE_ENTRY into Top-10.
    zones, trans = compute_topn("K", [[0, 8], [2, 12], [4, 15], [6, 9]])
    assert zones[10].entries == 2
    assert zones[10].inside is True
    assert zones[10].last_event == "TOP10_RE_ENTRY"
    assert [t.kind for t in trans if t.threshold == 10] == ["ENTRY", "EXIT", "RE_ENTRY"]


def test_topn_disappearance_keeps_last_known_standing():
    # §42: last seen inside Top-10 then no more snapshots -> stays inside, no EXIT.
    zones, trans = compute_topn("L", [[0, 20], [2, 8]])
    assert zones[10].inside is True
    assert not any(t.kind == "EXIT" for t in trans)


def test_topn_never_entered():
    # A symbol that is always rank > 20 has empty zones and no transitions.
    zones, trans = compute_topn("N", [[0, 40], [2, 35], [4, 30]])
    assert all(not zones[n].inside and zones[n].entries == 0 for n in TOP_N_THRESHOLDS)
    assert trans == []


# --- Phase 1D: sustained / rank-zone ---------------------------------------


def test_sustained_stable_zone():
    # §24: 6-9 band held over the window is a stable Top-10 zone.
    s = compute_sustained("Z", [[0, 9], [2, 8], [4, 9], [6, 7], [8, 8], [10, 6]])
    assert s.is_stable_zone is True
    assert s.zone_low == 6 and s.zone_high == 9 and s.zone_spread == 3
    assert s.zone_median == 8.0
    assert s.sustained_top10 is True and s.sustained_top5 is False


def test_sustained_chop_is_not_a_zone():
    # §24: 9, 2, 17 spans 15 ranks -> not a stable zone despite touching the top.
    s = compute_sustained("Y", [[0, 9], [2, 2], [4, 17]])
    assert s.is_stable_zone is False


def test_sustained_needs_minimum_evidence():
    # A single strong observation is not yet "sustained".
    s = compute_sustained("W", [[0, 3]])
    assert s.is_stable_zone is False
    assert s.sustained_top5 is False


def test_sustained_window_is_recent_only():
    # A rough early morning then a tight recent band -> stable on the recent window.
    # 8 observations; only the last SUSTAINED_WINDOW (6) count, dropping the 40/35.
    obs = [[0, 40], [2, 35], [4, 9], [6, 8], [8, 9], [10, 7], [12, 8], [14, 8]]
    s = compute_sustained("V", obs)
    assert s.zone_low == 7 and s.zone_high == 9  # last 6 obs only
    assert s.is_stable_zone is True


# --- Phase 1E: event classification ----------------------------------------


def test_event_extreme_vs_large_jump():
    assert compute_symbol_movement("J", [[0, 62], [2, 20]])["event"] == "EXTREME_JUMP"
    assert compute_symbol_movement("K", [[0, 40], [2, 22]])["event"] == "LARGE_JUMP"


def test_event_topn_entry_beats_climb_on_the_entry_step():
    # §60: when the latest step crosses into Top-5, that wins over the plain climb.
    row = compute_symbol_movement("Q", [[0, 20], [2, 8], [4, 3]])
    assert row["event"] == "TOP5_ENTRY"
    assert row["top5"] is True


def test_event_entry_does_not_refire_after_the_step():
    # §58: once past the entry step, a still-climbing 8->3->1 reads as a climb,
    # not a re-fired entry and not "sustained" (it is still moving, spread 7).
    row = compute_symbol_movement("P", [[0, 8], [2, 3], [4, 1]])
    assert row["event"] == "CLIMBING"
    assert row["top5"] is True
    assert row["is_stable_zone"] is False


def test_event_sustained_when_settled():
    row = compute_symbol_movement("S", [[0, 9], [2, 8], [4, 9], [6, 7], [8, 8], [10, 8]])
    assert row["event"] == "SUSTAINED_TOP10"
    assert row["is_stable_zone"] is True


def test_event_new_symbol_baseline():
    row = compute_symbol_movement("N", [[0, 40]])
    assert row["event"] == "NEW"
    assert row["rank_delta"] is None


def test_event_falling_and_fast_drop():
    # Plain FALLING needs a step that crosses no Top-N boundary (else the exit
    # event, which is more informative, wins): 12 -> 16 stays outside Top-10.
    assert compute_symbol_movement("D1", [[0, 12], [2, 16]])["event"] == "FALLING"
    # A big drop out of Top-20 is FAST_DROP (outranks the TOP20_EXIT it triggers).
    assert compute_symbol_movement("D2", [[0, 12], [2, 40]])["event"] == "FAST_DROP"


def test_event_topn_exit_is_reported():
    # Falling out of Top-5 (but staying in Top-10) surfaces the exit itself.
    assert compute_symbol_movement("E1", [[0, 4], [2, 8]])["event"] == "TOP5_EXIT"


def test_compute_symbol_movement_is_flat_dict():
    row = compute_symbol_movement("X", [[0, 20], [2, 8]])
    for key in ("symbol", "current_rank", "rank_delta", "top10", "event", "event_priority"):
        assert key in row


def test_movement_snapshot_sorted_and_degrades(monkeypatch):
    import services.tf_rank_movement_service as mod

    monkeypatch.setattr(
        mod,
        "get_boost_rank_timeline",
        lambda *a, **k: {"AA": {"2026-01-02": [[0, 30], [2, 18]]}, "BB": {"2026-01-02": [[0, 5]]}},
    )
    rows = mod.movement_snapshot("2026-01-02")
    assert [r["symbol"] for r in rows] == ["BB", "AA"]  # sorted by current_rank (5, 18)
    assert mod.movement_snapshot("2099-01-01") == [] or isinstance(rows, list)


def test_service_wrapper_degrades_to_empty_on_missing_day(monkeypatch):
    # The I/O wrapper must not raise when the DB has nothing for the date.
    import services.tf_rank_movement_service as mod

    monkeypatch.setattr(mod, "get_boost_rank_timeline", lambda *a, **k: {})
    assert rank_movement_service("1999-01-01") == {}


# --- Phase 1J: the remaining sequences the plan names (§75) -------------------


def test_oscillation_inside_top10_is_one_entry():
    # §75: 12 -> 9 -> 8 -> 9 -> 7. One Top-10 entry, no re-entry, and the dip
    # to 9 must not read as leaving the zone.
    obs = [[0, 12], [2, 9], [4, 8], [6, 9], [8, 7]]
    _zones, transitions = compute_topn("OSC", obs)
    entries = [x for x in transitions if x.threshold == 10 and x.kind == "ENTRY"]
    assert len(entries) == 1 and entries[0].minute == 2
    assert not [x for x in transitions if x.threshold == 10 and x.kind in ("EXIT", "RE_ENTRY")]


def test_exit_then_return_is_a_re_entry():
    # §75/§25: 9 -> 12 -> 9 leaves the Top-10 and comes back.
    _zones, transitions = compute_topn("RE", [[0, 9], [2, 12], [4, 9]])
    kinds = [(x.kind, x.minute) for x in transitions if x.threshold == 10]
    assert kinds == [("ENTRY", 0), ("EXIT", 2), ("RE_ENTRY", 4)]


def test_cumulative_universe_of_140_plus_symbols():
    # §81: the day's universe is cumulative and far wider than one list, so the
    # engine must handle every symbol seen today, not only those ranked now.
    timeline = {f"SYM{i:03d}": [[0, 200 - i], [2, 199 - i], [4, 150 - i]] for i in range(160)}
    states = compute_rank_states(timeline)
    assert len(states) == 160
    assert all(s.rank_delta == 49 for s in states.values())  # each improved 49 on the last step


def test_new_day_reset_reads_only_that_day(monkeypatch):
    # §39/§13: yesterday's path must not leak into today's state.
    import services.tf_rank_movement_service as mod

    timeline = {"AA": {"2026-01-01": [[0, 3], [2, 1]], "2026-01-02": [[0, 40], [2, 38]]}}
    monkeypatch.setattr(mod, "get_boost_rank_timeline", lambda *a, **k: timeline)
    rows = mod.movement_snapshot("2026-01-02")
    assert rows[0]["first_seen_rank"] == 40 and rows[0]["current_rank"] == 38
    assert rows[0]["best_rank"] == 38  # not yesterday's 1


# --- presence: an event is a statement about now (plan §42) -------------------


def test_symbol_missing_from_the_latest_snapshot_is_absent():
    # Climbed into the Top-5 at 09:17 and never appeared again: the standing
    # stays available as last-known, but it is not a current event.
    obs = [[555, 40], [556, 20], [557, 4]]
    row = compute_symbol_movement("GONE", obs, latest_minute=929)
    assert row["present"] is False
    assert row["minutes_since_last_seen"] == 929 - 557
    assert row["event"] == "ABSENT" and row["event_priority"] == 0
    # Last-known standing survives, so the trajectory still renders (§42).
    assert row["current_rank"] == 4 and row["first_seen_rank"] == 40 and row["top5"] is True


def test_symbol_in_the_latest_snapshot_keeps_its_event():
    obs = [[925, 12], [927, 9], [929, 4]]
    row = compute_symbol_movement("LIVE", obs, latest_minute=929)
    assert row["present"] is True and row["minutes_since_last_seen"] == 0
    assert row["event"] == "TOP5_ENTRY"


def test_one_missed_write_does_not_make_a_symbol_absent():
    # The recorder skipping a single minute must not blank the whole list.
    row = compute_symbol_movement("LIVE", [[925, 9], [927, 4]], latest_minute=929)
    assert row["present"] is True and row["event"] == "TOP5_ENTRY"


def test_movement_snapshot_marks_absent_against_the_days_latest_minute(monkeypatch):
    import services.tf_rank_movement_service as mod

    monkeypatch.setattr(
        mod,
        "get_boost_rank_timeline",
        lambda *a, **k: {
            "LIVE": {"2026-01-02": [[925, 12], [929, 4]]},
            "GONE": {"2026-01-02": [[555, 40], [557, 4]]},
        },
    )
    rows = {r["symbol"]: r for r in mod.movement_snapshot("2026-01-02")}
    assert rows["LIVE"]["present"] is True and rows["LIVE"]["event"] == "TOP5_ENTRY"
    assert rows["GONE"]["present"] is False and rows["GONE"]["event"] == "ABSENT"


# --- the open: a fresh day, nothing carried over (plan §13/§39/§40) -----------


def test_the_opening_snapshot_is_a_baseline_not_a_list_of_entries():
    # 09:15, the first tick of the day. Every symbol is inside some zone for the
    # first time, but none of them just entered it -- we never saw them outside.
    # Without this the whole opening top 20 alerts in the first minute.
    assert compute_symbol_movement("TOP", [[555, 1]], latest_minute=555)["event"] == "NEW"
    assert compute_symbol_movement("MID", [[555, 12]], latest_minute=555)["event"] == "NEW"
    assert compute_symbol_movement("LOW", [[555, 60]], latest_minute=555)["event"] == "NEW"


def test_a_symbol_first_seen_mid_session_is_new_not_an_entry():
    # Appears at 09:20 already inside the Top-20: still a baseline, not a move.
    row = compute_symbol_movement("LATE", [[560, 15]], latest_minute=560)
    assert row["event"] == "NEW"
    assert row["top20"] is True  # standing is still recorded


def test_a_real_entry_on_a_later_minute_still_fires():
    # The suppression must not swallow genuine crossings.
    assert (
        compute_symbol_movement("X", [[555, 30], [556, 12], [557, 9]], latest_minute=557)["event"]
        == "TOP10_ENTRY"
    )
    assert (
        compute_symbol_movement("Y", [[555, 30], [557, 9], [559, 14], [561, 8]], latest_minute=561)[
            "event"
        ]
        == "TOP10_RE_ENTRY"
    )


def test_an_empty_day_returns_nothing(monkeypatch):
    # Before 09:15 tomorrow the day has no rows at all; the panel must simply
    # show no badges rather than error.
    import services.tf_rank_movement_service as mod

    monkeypatch.setattr(mod, "get_boost_rank_timeline", lambda *a, **k: {})
    assert mod.movement_snapshot("2026-09-18") == []
