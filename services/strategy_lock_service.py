"""
Strategy Position Lock Manager — per-position threading locks (PRD V1 §17.3).

Prevents concurrent modifications to the same position from risk engine,
order poller, and webhook threads.
"""

import threading
from collections import defaultdict

# Module-level lock storage
_locks = defaultdict(threading.Lock)
_meta_lock = threading.Lock()  # protects _locks dict itself


def get_lock(strategy_id, strategy_type, symbol, exchange):
    """Get or create a lock for a specific position.

    Args:
        strategy_id: Strategy ID
        strategy_type: 'webhook' or 'chartink'
        symbol: Trading symbol
        exchange: Exchange code

    Returns:
        threading.Lock for this position key
    """
    key = f"{strategy_id}:{strategy_type}:{symbol}:{exchange}"
    with _meta_lock:
        return _locks[key]


def get_position_lock(position_id):
    """Get or create a lock for a specific position ID.

    Simpler variant when position ID is known.
    """
    key = f"pos:{position_id}"
    with _meta_lock:
        return _locks[key]


def cleanup_lock(strategy_id, strategy_type, symbol, exchange):
    """Remove a lock when position is closed (prevents memory leak)."""
    key = f"{strategy_id}:{strategy_type}:{symbol}:{exchange}"
    with _meta_lock:
        _locks.pop(key, None)


def cleanup_position_lock(position_id):
    """Remove a position-ID-based lock."""
    key = f"pos:{position_id}"
    with _meta_lock:
        _locks.pop(key, None)


def get_lock_count():
    """Get current number of active locks (for monitoring)."""
    with _meta_lock:
        return len(_locks)
