"""
Broker-local settings for Mudrex (HTTP pacing and bulk close spacing).

Prefer this file over environment variables for exchange/broker-specific tuning.
See ``broker_config.json`` beside this module; missing keys use code defaults.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from utils.logging import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "broker_config.json"

_DEFAULTS: dict = {
    "requests_per_second": 2.0,
    "close_position_delay_ms": 500,
}


@lru_cache(maxsize=1)
def load_mudrex_broker_config() -> dict:
    """Return merged config: JSON values override defaults for known keys only."""
    cfg = dict(_DEFAULTS)
    if not _CONFIG_PATH.is_file():
        return cfg
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning("[Mudrex] broker_config.json must be a JSON object; using defaults")
            return cfg
        for key in _DEFAULTS:
            if key in raw and raw[key] is not None:
                cfg[key] = raw[key]
    except (json.JSONDecodeError, OSError, TypeError) as e:
        logger.warning(f"[Mudrex] Could not read broker_config.json: {e}; using defaults")
    return cfg


def mudrex_requests_per_second() -> float:
    v = float(load_mudrex_broker_config()["requests_per_second"])
    return v if v > 0 else 2.0


def mudrex_close_position_delay_ms() -> int:
    v = int(load_mudrex_broker_config()["close_position_delay_ms"])
    return max(0, v)
