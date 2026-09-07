"""Sandbox position book: the session boundary must be compared in the DB's clock.

``sandbox_positions.updated_at`` is written by ``func.now()`` — UTC on the
default SQLite database. ``get_open_positions()`` used to build the session
boundary from naive *local* wall time, so on any host whose timezone is not
UTC the two clocks are mixed and positions last updated inside the UTC-offset
window (for IST, anything before 08:30 local: overnight crypto and
international-market trades) were silently dropped from the position book
(#1789).
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

# Repo root on the path before importing: test/sandbox/ is itself a package
# named "sandbox", so without this the import below resolves to this test
# package rather than the real one.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sandbox.session_boundary import last_session_expiry_utc  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")


class TestBoundaryConversion:
    """The boundary is a host wall-clock time resolved into naive UTC."""

    def test_utc_host_matches_naive_wall_clock(self):
        now = datetime(2026, 8, 12, 14, 7, tzinfo=UTC)
        assert last_session_expiry_utc("03:00", now) == datetime(2026, 8, 12, 3, 0)

    def test_afternoon_on_ist_host_is_previous_day_utc(self):
        # 14:07 IST == 08:37 UTC; the most recent 03:00 IST is 21:30 UTC the
        # day before. The old naive comparison used 03:00 as a raw wall value
        # and wrongly cut off updates from 21:30–03:00 UTC.
        now = datetime(2026, 8, 12, 14, 7, tzinfo=IST)
        assert last_session_expiry_utc("03:00", now) == datetime(2026, 8, 11, 21, 30)

    def test_before_expiry_on_ist_host_rolls_back_another_day(self):
        # 01:00 IST is still the previous trading session.
        now = datetime(2026, 8, 12, 1, 0, tzinfo=IST)
        assert last_session_expiry_utc("03:00", now) == datetime(2026, 8, 10, 21, 30)

    def test_negative_offset_host(self):
        # 03:00 EDT (August, UTC-4) == 07:00 UTC the same day.
        now = datetime(2026, 8, 12, 14, 7, tzinfo=NY)
        assert last_session_expiry_utc("03:00", now) == datetime(2026, 8, 12, 7, 0)

    def test_offset_subtracted_for_every_timezone(self):
        """Boundary(UTC) == boundary wall time minus the host offset."""
        for tz, offset_hours in ((UTC, 0), (IST, 5.5), (NY, -4)):
            now = datetime(2026, 8, 12, 14, 7, tzinfo=tz)
            resolved = last_session_expiry_utc("03:00", now)
            naive_today = datetime(2026, 8, 12, 3, 0)
            assert resolved == naive_today - timedelta(hours=offset_hours)


TEST_USER = "TEST_SB_BOUNDARY_1"


@pytest.fixture()
def positions_around_boundary():
    """Rows straddling the session boundary, so the assertions hold whatever
    wall clock and host timezone the suite runs under."""
    from database.sandbox_db import SandboxPositions, db_session

    SandboxPositions.query.filter_by(user_id=TEST_USER).delete()
    db_session.commit()

    boundary = last_session_expiry_utc("03:00", datetime.now().astimezone())
    rows = [
        # Open MIS updated after the UTC boundary -> current session, shown.
        SandboxPositions(
            user_id=TEST_USER,
            symbol="SBTEST1",
            exchange="NSE",
            product="MIS",
            quantity=10,
            average_price=Decimal("100"),
            updated_at=boundary + timedelta(minutes=30),
        ),
        # Open MIS updated before the UTC boundary -> previous session, hidden.
        SandboxPositions(
            user_id=TEST_USER,
            symbol="SBTEST2",
            exchange="NSE",
            product="MIS",
            quantity=10,
            average_price=Decimal("100"),
            updated_at=boundary - timedelta(minutes=30),
        ),
        # Open NRML updated before the boundary -> carried forward, shown.
        SandboxPositions(
            user_id=TEST_USER,
            symbol="SBTEST3",
            exchange="NSE",
            product="NRML",
            quantity=10,
            average_price=Decimal("100"),
            updated_at=boundary - timedelta(minutes=30),
        ),
        # Closed long ago with no today-PnL -> hidden.
        SandboxPositions(
            user_id=TEST_USER,
            symbol="SBTEST4",
            exchange="NSE",
            product="MIS",
            quantity=0,
            average_price=Decimal("100"),
            updated_at=boundary - timedelta(minutes=30),
        ),
    ]
    db_session.add_all(rows)
    db_session.commit()
    yield boundary
    SandboxPositions.query.filter_by(user_id=TEST_USER).delete()
    db_session.commit()


def test_position_book_filters_on_the_utc_boundary(positions_around_boundary):
    """get_open_positions() keeps exactly the rows the UTC boundary admits."""
    from sandbox.position_manager import PositionManager

    success, response, status = PositionManager(TEST_USER).get_open_positions(update_mtm=False)
    assert success is True and status == 200
    shown = {row["symbol"] for row in response["data"]}
    assert shown == {"SBTEST1", "SBTEST3"}
