"""Mode normalization helpers for the WebSocket proxy.

Single source of truth for converting client- or topic-supplied "mode" values
into the canonical (numeric, label) pair used internally and on the wire.

Accepts:
    - int: 1, 2, 3
    - str: "LTP" / "Quote" / "Depth" — case-insensitive ("ltp", "QUOTE",
      "DePtH" all valid; whitespace is stripped).

Returns: (numeric_mode, canonical_label) where labels are always
"LTP" / "Quote" / "Depth" so API responses stay consistent regardless of
input casing.

Raises ValueError for invalid values (out-of-range int, unknown string,
empty string, wrong type — except non-int / non-str which raise TypeError).
Use normalize_mode_or_none() for hot paths that prefer to log+skip instead
of raising (e.g. the ZMQ topic parser in WebSocketProxy.zmq_listener).

This replaces the two prior in-class mappings (MODE_MAP uppercase-only and
mode_mapping CapCase-only) which silently disagreed and let documented
requests like {"mode": "QUOTE"} pass through to broker adapters as the raw
string. See issue #1375.
"""

_MODE_CANONICAL: dict[int, str] = {1: "LTP", 2: "Quote", 3: "Depth"}
_MODE_BY_UPPER_LABEL: dict[str, int] = {"LTP": 1, "QUOTE": 2, "DEPTH": 3}


def normalize_mode(value) -> tuple[int, str]:
    """Return (numeric_mode, canonical_label) for any accepted mode input.

    Raises:
        ValueError: int out of range, unknown string, or empty string.
        TypeError:  value is neither int nor str (or is a bool, which is
                    a subclass of int but disallowed here for safety).
    """
    if isinstance(value, bool):  # bool is a subclass of int — exclude explicitly
        raise TypeError(f"Mode must be int or str, got bool ({value!r})")
    if isinstance(value, int):
        if value not in _MODE_CANONICAL:
            raise ValueError(
                f"Invalid mode {value}; expected 1 (LTP), 2 (Quote), or 3 (Depth)"
            )
        return value, _MODE_CANONICAL[value]
    if isinstance(value, str):
        upper = value.strip().upper()
        if upper not in _MODE_BY_UPPER_LABEL:
            raise ValueError(
                f"Invalid mode {value!r}; expected 'LTP', 'Quote', or 'Depth' (case-insensitive)"
            )
        numeric = _MODE_BY_UPPER_LABEL[upper]
        return numeric, _MODE_CANONICAL[numeric]
    raise TypeError(f"Mode must be int or str, got {type(value).__name__}")


def normalize_mode_or_none(value) -> tuple[int, str] | None:
    """Non-raising variant for hot paths (e.g. ZMQ topic parser).

    Returns None if value is invalid; caller is expected to log and skip.
    """
    try:
        return normalize_mode(value)
    except (ValueError, TypeError):
        return None


# Convenience re-exports for callers that still want the raw mappings.
# Kept private-by-convention (single underscore) so new code is steered to
# the functions above instead.
MODE_BY_UPPER_LABEL = dict(_MODE_BY_UPPER_LABEL)  # {"LTP": 1, "QUOTE": 2, "DEPTH": 3}
MODE_CANONICAL = dict(_MODE_CANONICAL)            # {1: "LTP", 2: "Quote", 3: "Depth"}
