"""Tests for sandbox session boundary resolution and MIS catch-up filtering."""

import os
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sandbox.session_boundary import last_session_expiry_utc  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def test_last_session_expiry_utc_after_boundary_ist():
    """After 03:00 IST the boundary is today's 03:00 IST expressed in UTC."""
    now = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
    boundary = last_session_expiry_utc("03:00", now)
    # 03:00 IST on Aug 18 = 21:30 UTC on Aug 17
    assert boundary == datetime(2026, 8, 17, 21, 30)


def test_last_session_expiry_utc_before_boundary_ist():
    """Before 03:00 IST the boundary is yesterday's 03:00 IST in UTC."""
    now = datetime(2026, 8, 18, 1, 0, tzinfo=IST)
    boundary = last_session_expiry_utc("03:00", now)
    # 03:00 IST on Aug 17 = 21:30 UTC on Aug 16
    assert boundary == datetime(2026, 8, 16, 21, 30)


def test_reopened_position_not_stale_when_updated_after_boundary():
    """Row reuse keeps old created_at; updated_at after boundary means live MIS."""
    session_expiry = "03:00"
    now = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
    boundary = last_session_expiry_utc(session_expiry, now)

    updated_at = datetime(2026, 8, 18, 4, 30)  # reopened today (UTC)
    quantity = 50

    is_stale = quantity != 0 and updated_at < boundary
    assert not is_stale


def test_overnight_mis_still_stale_when_not_updated_since_boundary():
    """Genuine overnight MIS: non-zero qty and updated_at before session boundary."""
    session_expiry = "03:00"
    now = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
    boundary = last_session_expiry_utc(session_expiry, now)

    updated_at = datetime(2026, 8, 16, 12, 0)
    quantity = -25

    is_stale = quantity != 0 and updated_at < boundary
    assert is_stale
