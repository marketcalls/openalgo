"""Unit tests for utils/ist_time.py."""

from datetime import datetime, timezone, timedelta

import pytest

from utils.ist_time import (
    IST,
    fmt_iso_ist,
    fmt_orderbook,
    fmt_tradebook,
    now_utc,
    parse_broker_ist,
    to_epoch_ms,
    to_ist,
)


def test_now_utc_is_aware():
    n = now_utc()
    assert n.tzinfo is not None
    assert n.utcoffset().total_seconds() == 0


def test_to_ist_from_epoch_seconds():
    # 2026-05-06 09:15:00 IST == 03:45:00 UTC
    epoch_s = int(datetime(2026, 5, 6, 3, 45, 0, tzinfo=timezone.utc).timestamp())
    out = to_ist(epoch_s)
    assert out.tzinfo == IST
    assert out.hour == 9 and out.minute == 15


def test_to_ist_from_epoch_ms():
    epoch_ms = int(datetime(2026, 5, 6, 3, 45, 0, tzinfo=timezone.utc).timestamp() * 1000)
    out = to_ist(epoch_ms)
    assert out.hour == 9 and out.minute == 15


def test_to_ist_from_naive_datetime_assumes_utc():
    naive = datetime(2026, 5, 6, 3, 45, 0)
    out = to_ist(naive)
    assert out.hour == 9 and out.minute == 15


def test_to_ist_from_aware_datetime_preserves():
    aware = datetime(2026, 5, 6, 9, 15, 0, tzinfo=IST)
    out = to_ist(aware)
    assert out == aware


def test_fmt_orderbook_roundtrip():
    # Use a fixed UTC instant
    utc_dt = datetime(2026, 5, 6, 9, 0, 30, tzinfo=timezone.utc)
    s = fmt_orderbook(utc_dt)
    # 09:00:30 UTC + 05:30 = 14:30:30 IST
    assert s == "06-May-2026 14:30:30"


def test_fmt_tradebook_strips_date():
    utc_dt = datetime(2026, 5, 6, 9, 0, 30, tzinfo=timezone.utc)
    assert fmt_tradebook(utc_dt) == "14:30:30"


def test_fmt_iso_ist_carries_offset():
    utc_dt = datetime(2026, 5, 6, 9, 0, 30, tzinfo=timezone.utc)
    assert fmt_iso_ist(utc_dt) == "2026-05-06T14:30:30+05:30"


def test_parse_broker_ist_orderbook_format():
    out = parse_broker_ist("06-May-2026 14:30:30")
    # Returns UTC; 14:30:30 IST = 09:00:30 UTC
    assert out.tzinfo == timezone.utc
    assert out.hour == 9 and out.minute == 0 and out.second == 30


def test_parse_broker_ist_tradebook_format_uses_today():
    out = parse_broker_ist("14:30:30")
    today_ist = datetime.now(IST).date()
    assert out.tzinfo == timezone.utc
    # The date came from today's IST date — verify that's what we got
    out_ist = out.astimezone(IST)
    assert out_ist.date() == today_ist


def test_parse_broker_ist_invalid_raises():
    with pytest.raises(ValueError):
        parse_broker_ist("not a timestamp")


def test_to_epoch_ms_roundtrip():
    utc_dt = datetime(2026, 5, 6, 0, 0, 0, tzinfo=timezone.utc)
    ms = to_epoch_ms(utc_dt)
    # Sanity: 2026 epoch is in the trillions ms range
    assert ms > 1_700_000_000_000


def test_to_ist_rejects_unsupported_type():
    with pytest.raises(TypeError):
        to_ist("not a timestamp")
