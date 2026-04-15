# services/replay_service.py
"""
Replay Service - Manages replay session state for sandbox paper trading.

Replay mode allows sandbox to use uploaded historical data (DuckDB)
instead of live broker prices for MTM and order execution.

State is stored in-memory with persistence to the sandbox config DB.
"""

import threading

from utils.logging import get_logger

logger = get_logger(__name__)

# In-memory replay session state (thread-safe)
_replay_lock = threading.Lock()
_replay_state = {
    "enabled": False,
    "status": "stopped",  # stopped, running, paused
    "current_ts": None,   # epoch seconds
    "start_ts": None,     # epoch seconds
    "end_ts": None,       # epoch seconds
    "speed": 1.0,         # multiplier (1.0 = real-time, 60.0 = 1 minute per second)
    "universe_mode": "all",  # "all" or "active"
}

# Background thread for advancing replay clock
_replay_thread = None
_stop_event = threading.Event()


def get_replay_session() -> dict:
    """Get current replay session state."""
    with _replay_lock:
        return dict(_replay_state)


def configure_replay(
    start_ts: int | None = None,
    end_ts: int | None = None,
    speed: float | None = None,
    universe_mode: str | None = None,
) -> dict:
    """
    Configure replay parameters.
    
    Args:
        start_ts: Start timestamp (epoch seconds)
        end_ts: End timestamp (epoch seconds)
        speed: Speed multiplier (1.0 = advance 1 min/sec, 60.0 = advance 1 hour/sec)
        universe_mode: 'all' or 'active'
    
    Returns:
        Updated replay session state
    """
    with _replay_lock:
        if start_ts is not None:
            _replay_state["start_ts"] = int(start_ts)
            # Set current_ts to start if not running
            if _replay_state["status"] in ("stopped", "paused"):
                _replay_state["current_ts"] = int(start_ts)
        
        if end_ts is not None:
            _replay_state["end_ts"] = int(end_ts)
        
        if speed is not None:
            _replay_state["speed"] = max(0.1, min(float(speed), 3600.0))
        
        if universe_mode is not None:
            if universe_mode in ("all", "active"):
                _replay_state["universe_mode"] = universe_mode
        
        logger.info(f"Replay configured: start={_replay_state['start_ts']}, "
                     f"end={_replay_state['end_ts']}, speed={_replay_state['speed']}x")
        
        return dict(_replay_state)


def start_replay() -> tuple[bool, str, dict]:
    """
    Start or resume the replay clock.
    
    Returns:
        (success, message, state)
    """
    global _replay_thread
    
    with _replay_lock:
        if _replay_state["start_ts"] is None or _replay_state["end_ts"] is None:
            return False, "Start and end timestamps must be configured first", dict(_replay_state)
        
        if _replay_state["start_ts"] >= _replay_state["end_ts"]:
            return False, "Start time must be before end time", dict(_replay_state)
        
        if _replay_state["status"] == "running":
            return True, "Replay is already running", dict(_replay_state)
        
        # If stopped, reset current_ts to start
        if _replay_state["status"] == "stopped":
            _replay_state["current_ts"] = _replay_state["start_ts"]
        
        _replay_state["enabled"] = True
        _replay_state["status"] = "running"
    
    # Ensure previous thread has exited before starting a new one
    if _replay_thread is not None and _replay_thread.is_alive():
        _replay_thread.join(timeout=1.0)
    
    # Start background thread
    _stop_event.clear()
    _replay_thread = threading.Thread(target=_replay_clock_loop, daemon=True, name="replay-clock")
    _replay_thread.start()
    
    logger.info("Replay started")
    return True, "Replay started", get_replay_session()


def pause_replay() -> tuple[bool, str, dict]:
    """Pause the replay clock."""
    with _replay_lock:
        if _replay_state["status"] != "running":
            return False, "Replay is not running", dict(_replay_state)
        
        _replay_state["status"] = "paused"
    
    _stop_event.set()
    
    logger.info("Replay paused")
    return True, "Replay paused", get_replay_session()


def stop_replay() -> tuple[bool, str, dict]:
    """Stop the replay and reset."""
    _stop_event.set()
    
    with _replay_lock:
        _replay_state["enabled"] = False
        _replay_state["status"] = "stopped"
        _replay_state["current_ts"] = _replay_state.get("start_ts")
    
    logger.info("Replay stopped")
    return True, "Replay stopped", get_replay_session()


def seek_replay(target_ts: int) -> tuple[bool, str, dict]:
    """
    Seek to a specific timestamp.
    
    Args:
        target_ts: Target timestamp (epoch seconds)
    """
    with _replay_lock:
        start = _replay_state.get("start_ts")
        end = _replay_state.get("end_ts")
        
        if start is None or end is None:
            return False, "Replay not configured", dict(_replay_state)
        
        if target_ts < start or target_ts > end:
            return False, f"Target must be between start ({start}) and end ({end})", dict(_replay_state)
        
        _replay_state["current_ts"] = int(target_ts)
    
    logger.info(f"Replay seeked to {target_ts}")
    return True, "Replay seeked", get_replay_session()


def _replay_clock_loop():
    """Background thread that advances the replay clock."""
    TICK_INTERVAL = 1.0  # seconds between ticks
    
    while not _stop_event.is_set():
        with _replay_lock:
            if _replay_state["status"] != "running":
                break
            
            current = _replay_state.get("current_ts")
            end = _replay_state.get("end_ts")
            speed = _replay_state.get("speed", 1.0)
            
            if current is None or end is None:
                break
            
            # Advance by speed * 60 seconds per tick (1 tick = 1 real second)
            # speed=1.0 means advance 1 minute of market time per real second
            new_ts = current + int(speed * 60)
            
            if new_ts >= end:
                _replay_state["current_ts"] = end
                _replay_state["status"] = "stopped"
                _replay_state["enabled"] = False
                logger.info("Replay reached end")
                break
            
            _replay_state["current_ts"] = new_ts
        
        _stop_event.wait(TICK_INTERVAL)
    
    logger.debug("Replay clock loop exited")
