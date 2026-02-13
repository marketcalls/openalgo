import os
import sys
import pandas as pd
import pytz
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.datetime_utils import get_ist_now, to_ist_epoch, IST

def test_ist_now():
    """Verify that get_ist_now returns localized IST time."""
    print("Testing get_ist_now()...")
    now = get_ist_now()
    print(f"Current IST Now: {now}")
    assert now.tzinfo is not None
    assert str(now.tzinfo) == "Asia/Kolkata"
    print("SUCCESS: get_ist_now() returns localized IST.\n")

def test_to_ist_epoch():
    """Verify that to_ist_epoch treats naive datetime as IST and converts correctly to UTC epoch."""
    print("Testing to_ist_epoch()...")
    # 2026-02-11 09:15:00 IST
    naive_dt = datetime(2026, 2, 11, 9, 15, 0)
    epoch = to_ist_epoch(naive_dt)
    
    # Expected epoch for 2026-02-11 09:15:00 IST
    # IST is UTC+5:30. So 09:15 IST = 03:45 UTC.
    localized = IST.localize(naive_dt)
    expected_epoch = int(localized.timestamp())
    
    print(f"Naive DT: {naive_dt}")
    print(f"Calculated Epoch: {epoch}")
    print(f"Expected Epoch: {expected_epoch}")
    
    assert epoch == expected_epoch
    
    # Test with localized Timestamp
    ts_ist = pd.Timestamp(naive_dt, tz='Asia/Kolkata')
    assert to_ist_epoch(ts_ist) == expected_epoch
    
    # Test with string
    assert to_ist_epoch("2026-02-11 09:15:00") == expected_epoch
    
    print("SUCCESS: to_ist_epoch() correctly handles various input formats.\n")

def test_daily_offset_logic():
    """Verify the daily offset logic used in broker adapters."""
    print("Testing daily offset logic (UTC+5:30 for daily candles)...")
    # Simulate a daily candle timestamp (usually midnight UTC)
    utc_midnight = pd.to_datetime("2026-02-11 00:00:00")
    ist_adjusted = utc_midnight + pd.Timedelta(hours=5, minutes=30)
    
    # This result should be 2026-02-11 05:30:00 IST (naive)
    epoch = to_ist_epoch(ist_adjusted)
    
    # 05:30 IST is 00:00 UTC
    assert epoch == int(utc_midnight.timestamp())
    print("SUCCESS: Daily offset + to_ist_epoch correctly maps back to UTC midnight epoch.\n")

if __name__ == "__main__":
    try:
        test_ist_now()
        test_to_ist_epoch()
        test_daily_offset_logic()
        print("ALL TESTS PASSED!")
    except Exception as e:
        print(f"TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
