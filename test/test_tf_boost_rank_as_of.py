"""get_boost_symbols rank cutoff.

Guards the point-in-time property the ISI backtest's Top-N slice depends on:
with `rank_as_of` set, the universe is the list as of that time only — a stock
that climbed the ranks later in the session must not be pulled forward into the
top of the list (which is what made whole-day ranking optimistic).
"""

import database.tf_boost_db as tf_boost_db
from database.tf_boost_db import (
    get_boost_rank_timeline,
    get_boost_symbols,
    get_connection,
    init_tf_boost_database,
)


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(tf_boost_db, "TF_BOOST_DB_PATH", str(tmp_path / "boost.duckdb"))
    init_tf_boost_database()
    # 09:15 and 09:20 are the only snapshots at/before a 09:20 cutoff. LATE is
    # absent then and takes rank 1 at 14:00; NEWCOMER only ever appears at 14:00.
    rows = [
        ("2026-08-10", "2026-08-10 09:15:00", 2, "EARLY"),
        ("2026-08-10", "2026-08-10 09:15:00", 3, "MID"),
        ("2026-08-10", "2026-08-10 09:20:00", 2, "MID"),
        ("2026-08-10", "2026-08-10 09:20:00", 3, "EARLY"),
        ("2026-08-10", "2026-08-10 14:00:00", 1, "LATE"),
        ("2026-08-10", "2026-08-10 14:00:00", 2, "NEWCOMER"),
        ("2026-08-10", "2026-08-10 14:00:00", 3, "EARLY"),
        # A day whose scraper started late: first snapshot is after the cutoff.
        ("2026-08-07", "2026-08-07 09:30:00", 1, "LATESTART"),
    ]
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO tf_boost_snapshots "
            "(snapshot_date, snapshot_time, list_type, rank, symbol) "
            "VALUES (?, ?, 'intraday_boost', ?, ?)",
            rows,
        )


def test_rank_as_of_uses_only_the_cutoff_snapshot(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    # Whole-day ranking: LATE reached rank 1, so it sorts first — hindsight.
    assert get_boost_symbols("2026-08-10", "2026-08-10")[0] == "LATE"

    # As of 09:20: the 09:20 snapshot's order, and nothing that arrived later.
    cut = get_boost_symbols("2026-08-10", "2026-08-10", rank_as_of="09:20")
    assert cut == ["MID", "EARLY"]

    # An exact-snapshot cutoff and one between snapshots resolve the same way.
    assert get_boost_symbols("2026-08-10", "2026-08-10", rank_as_of="09:22") == cut
    assert get_boost_symbols("2026-08-10", "2026-08-10", rank_as_of="09:15") == ["EARLY", "MID"]


def test_day_starting_after_the_cutoff_falls_back_to_its_first_snapshot(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    # Dropping the day entirely would silently shrink a multi-day universe.
    assert get_boost_symbols("2026-08-07", "2026-08-07", rank_as_of="09:20") == ["LATESTART"]


def test_rank_timeline_is_per_day_and_time_ordered(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    timeline = get_boost_rank_timeline("2026-08-10", "2026-08-10")

    # Minute-of-day, ascending — what the per-signal top-N gate scans.
    assert timeline["EARLY"]["2026-08-10"] == [[555, 2], [560, 3], [840, 3]]
    # A symbol that only shows up later has no pair before it did.
    assert timeline["NEWCOMER"]["2026-08-10"] == [[840, 2]]
    # Days outside the window are not included.
    assert "LATESTART" not in timeline


def test_bad_cutoff_is_ignored_not_fatal(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert get_boost_symbols("2026-08-10", "2026-08-10", rank_as_of="oops") == get_boost_symbols(
        "2026-08-10", "2026-08-10"
    )
