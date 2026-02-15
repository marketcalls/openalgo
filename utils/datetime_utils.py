import pandas as pd
import pytz
from datetime import datetime
from typing import Any

IST = pytz.timezone("Asia/Kolkata")

def get_ist_now() -> pd.Timestamp:
    """Return current time as localized IST Timestamp."""
    return pd.Timestamp.now(tz=IST)

def get_ist_date_str() -> str:
    """Return current IST date as YYYY-MM-DD string."""
    return get_ist_now().strftime("%Y-%m-%d")

def to_ist_epoch(dt: Any) -> int:
    """
    Convert a datetime/Timestamp to Unix epoch, treating naive datetimes as IST.
    
    Args:
        dt: datetime, pandas.Timestamp, or YYYY-MM-DD string.
    """
    if isinstance(dt, str):
        dt = pd.to_datetime(dt)
    elif isinstance(dt, (int, float)):
        return int(dt)
        
    # Handle pure date objects (convert to midnight)
    if not hasattr(dt, 'hour') and hasattr(dt, 'year'):
        dt = pd.Timestamp(dt)
        
    # If naive, assume IST
    if dt.tzinfo is None:
        if isinstance(dt, pd.Timestamp):
            dt = dt.tz_localize(IST)
        else:
            dt = IST.localize(dt)
            
    # Convert to UTC and get timestamp
    if isinstance(dt, pd.Timestamp):
        return int(dt.tz_convert(pytz.UTC).timestamp())
    return int(dt.astimezone(pytz.UTC).timestamp())

def to_ist_epoch_series(s: pd.Series) -> pd.Series:
    """
    Vectorized version of to_ist_epoch for pandas Series.
    Treats naive timestamps as IST and converts to Unix epoch.
    """
    if s.empty:
        return s
        
    # Ensure it's datetime64
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s)
        
    # If naive, localize to IST (UTC+5:30)
    if s.dt.tz is None:
        s = s.dt.tz_localize(IST)
    else:
        # If already localized, convert to IST for consistency
        s = s.dt.tz_convert(IST)
        
    # Convert to UTC and get Unix epoch (seconds)
    return s.dt.tz_convert(pytz.UTC).astype("int64") // 10**9
