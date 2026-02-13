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
