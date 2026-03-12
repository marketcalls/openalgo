# 🐛 Bug Report: Bare `except:` clause hides conversion errors in `_safe_timestamp()`

## Description
While adding docstrings and reviewing the `database` module, I spotted a bare `except:` clause in `database/historify_db.py`. Using a bare `except:` is generally considered an anti-pattern as it catches *all* exceptions, including `SystemExit` and `KeyboardInterrupt`, which can silently swallow critical errors and make debugging production issues very difficult.

## Bug Location
**File:** `database/historify_db.py`
**Function:** `_safe_timestamp(val)`
**Line:** ~1858

```python
def _safe_timestamp(val) -> str | None:
    """Convert timestamp to ISO string, handling NaT/None values."""
    if val is None:
        return None
    if pd.isna(val):
        return None
    try:
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return str(val)
    except:  # <--- BARE EXCEPT HERE
        return None
```

## Impact
If `val.isoformat()` or `str(val)` fail due to some underlying issues (like memory errors, attribute access permission, or even if the user attempts to terminate the process), the error will be completely absorbed without being logged. The function will simply return `None`, making it incredibly difficult to trace back where the timestamp data loss occurred.

## Proposed Fix
We should replace the bare `except:` with a specific exception (like `Exception` or ideally `TypeError`, `ValueError`). In addition, if we expect intermittent failures on formatting, we should log a warning with context, instead of silently returning `None`.

```python
    try:
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return str(val)
    except Exception as e:
        logger.warning(f"Failed to convert timestamp {val} to ISO format: {e}")
        return None
```

## Tasks
- [ ] Update `database/historify_db.py` to catch `Exception` instead of bare `except:`.
- [ ] Add `logger.warning` for visibility when conversion fails.
- [ ] Scan the rest of the codebase for other bare `except:` blocks implicitly returning `None` and fix them.

---
*Created as part of the Week 1 Security & Design Integration Strategy.*
