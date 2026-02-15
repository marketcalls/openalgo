import os
import sys
import pandas as pd
import pytz
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.datetime_utils import get_ist_now, to_ist_epoch, to_ist_epoch_series, IST

def test_get_ist_now():
    """Verify that get_ist_now returns localized IST time."""
    now = get_ist_now()
    # Check that it's localized correctly
    assert now.tzinfo is not None
    assert str(now.tzinfo) == "Asia/Kolkata" or now.tzinfo.zone == "Asia/Kolkata"
    
    # Verify it matches current localized time roughly
    system_now = pd.Timestamp.now(tz=IST)
    assert abs((now - system_now).total_seconds()) < 5

def test_to_ist_epoch_naive():
    """Verify that to_ist_epoch treats naive datetime as IST."""
    naive_dt = datetime(2026, 2, 11, 9, 15, 0)
    epoch = to_ist_epoch(naive_dt)
    
    # 09:15 IST is 03:45 UTC
    expected_epoch = int(IST.localize(naive_dt).timestamp())
    assert epoch == expected_epoch

def test_to_ist_epoch_string():
    """Verify that to_ist_epoch handles ISO date strings."""
    date_str = "2026-02-11 09:15:00"
    epoch = to_ist_epoch(date_str)
    
    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    expected_epoch = int(IST.localize(dt).timestamp())
    assert epoch == expected_epoch

def test_to_ist_epoch_series_vectorized():
    """Verify that to_ist_epoch_series correctly converts a pandas Series."""
    dates = [
        "2026-02-11 09:15:00",
        "2026-02-11 15:30:00",
        "2026-02-12 00:00:00"
    ]
    s = pd.Series(pd.to_datetime(dates))
    epochs = to_ist_epoch_series(s)
    
    assert len(epochs) == 3
    assert isinstance(epochs, pd.Series)
    
    # Verify individual values
    for i, date_str in enumerate(dates):
        expected = to_ist_epoch(date_str)
        assert epochs.iloc[i] == expected

def test_to_ist_epoch_series_localized():
    """Verify that to_ist_epoch_series handles already localized Series."""
    dt = pd.to_datetime("2026-02-11 09:15:00").tz_localize("UTC")
    s = pd.Series([dt])
    epochs = to_ist_epoch_series(s)
    
    # 09:15 UTC is 14:45 IST. 
    # to_ist_epoch_series converts to UTC epoch regardless of input TZ
    expected = int(dt.timestamp())
    assert epochs.iloc[0] == expected

def test_to_ist_epoch_series_empty():
    """Verify that to_ist_epoch_series handles empty Series."""
    s = pd.Series([], dtype="datetime64[ns]")
    result = to_ist_epoch_series(s)
    assert result.empty

def test_to_ist_epoch_series_numeric():
    """Verify that to_ist_epoch_series preserves numeric inputs (epochs)."""
    epochs = [1739245500, 1739245560]
    s = pd.Series(epochs)
    result = to_ist_epoch_series(s)
    
    assert list(result) == epochs

if __name__ == "__main__":
    # This allows running the test file directly with 'python test/test_datetime_utils.py'
    # It will produce formatted output similar to the 'pytest' command.
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts="]))
