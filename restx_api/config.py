import os
from limits import parse

DEFAULT_RATE_LIMIT = "10 per second"
def _get_valid_rate_limit():
    raw = os.getenv("API_RATE_LIMIT", DEFAULT_RATE_LIMIT)
    try:
        parse(raw) # validates format
        return raw
    except Exception:
        print(f"Invalid API_RATE_LIMIT='{raw}', falling back to default.")
        return DEFAULT_RATE_LIMIT

API_RATE_LIMIT = _get_valid_rate_limit()