"""Market timings are IST epochs, whatever time zone the host runs in.

get_market_timings_for_date() anchors each exchange's offsets to midnight on the
requested date. Midnight has to be IST midnight: the offsets are IST wall-clock
times and docs/api/market-calendar/timings.md publishes 1766115900000 (09:15
IST) as NSE's open on 2025-12-19. Native installs on a UTC VPS, or anywhere
outside India, must return the same epoch as the Docker image, which pins
TZ=Asia/Kolkata.
"""

import os
import time
from datetime import date

import pytest

from database import market_calendar_db as mcdb


class _NoHoliday:
    holiday_date = None

    class query:
        @staticmethod
        def filter(*_args, **_kwargs):
            class _Result:
                @staticmethod
                def first():
                    return None

            return _Result


@pytest.fixture
def host_tz(monkeypatch):
    original = os.environ.get("TZ")

    def _set(tz):
        monkeypatch.setenv("TZ", tz)
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is POSIX only")
@pytest.mark.parametrize("tz", ["Asia/Kolkata", "UTC", "America/New_York", "Europe/Paris"])
def test_timings_are_ist_epochs_on_any_host(monkeypatch, host_tz, tz):
    host_tz(tz)
    monkeypatch.setattr(mcdb, "Holiday", _NoHoliday)
    monkeypatch.setattr(mcdb, "_get_timing_offsets", lambda: mcdb.DEFAULT_MARKET_TIMINGS)
    mcdb.clear_market_calendar_cache()

    timings = {t["exchange"]: t for t in mcdb.get_market_timings_for_date(date(2025, 12, 19))}
    mcdb.clear_market_calendar_cache()

    # The values published in docs/api/market-calendar/timings.md.
    assert timings["NSE"]["start_time"] == 1766115900000  # 09:15 IST
    assert timings["NSE"]["end_time"] == 1766138400000  # 15:30 IST
    assert timings["CDS"]["start_time"] == 1766115000000  # 09:00 IST
